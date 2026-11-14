from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from .models import Comment, ServiceRequest, WorkOrder


@transaction.atomic
def service_request_create(*, requester, category, title, description, location, priority):
    item = ServiceRequest(
        requester=requester,
        category=category,
        title=title,
        description=description,
        location=location,
        priority=priority,
    )
    item.full_clean()
    item.save()
    return item


@transaction.atomic
def service_request_update(*, item, actor, category, title, description, location, priority):
    locked = ServiceRequest.objects.select_for_update().get(id=item.id)
    if actor != locked.requester and not actor.is_staff:
        raise PermissionDenied("You cannot edit this request.")
    if locked.status != ServiceRequest.Status.OPEN and not actor.is_staff:
        raise ValidationError("Only an open request can be edited.")
    locked.category, locked.title = category, title
    locked.description, locked.location, locked.priority = description, location, priority
    locked.full_clean()
    locked.save(update_fields=[
        "category", "title", "description", "location", "priority", "updated_at"
    ])
    return locked


@transaction.atomic
def comment_create(*, item, author, body):
    comment = Comment(service_request=item, author=author, body=body)
    comment.full_clean()
    comment.save()
    return comment


@transaction.atomic
def service_request_assign(*, item, actor, technician):
    if not actor.is_staff:
        raise PermissionDenied("Only staff members can assign service requests.")
    if not technician or not technician.is_active or not technician.is_staff:
        raise ValidationError("Technician must be an active staff member.")

    locked = ServiceRequest.objects.select_for_update().get(id=item.id)
    work_order, _ = WorkOrder.objects.update_or_create(
        service_request=locked,
        defaults={
            "technician": technician,
            "started_at": timezone.now(),
        },
    )
    locked.status = ServiceRequest.Status.ASSIGNED
    locked.full_clean()
    locked.save(update_fields=["status", "updated_at"])
    return work_order


@transaction.atomic
def service_request_resolve(*, item, actor, work_notes, resolution_summary=""):
    locked = ServiceRequest.objects.select_for_update().get(id=item.id)
    try:
        work_order = locked.work_order
    except WorkOrder.DoesNotExist:
        raise ValidationError("Cannot resolve a service request that has not been assigned.")

    is_assigned_tech = work_order.technician_id == actor.id
    if not (actor.is_staff or is_assigned_tech):
        raise PermissionDenied("Only staff or the assigned technician can resolve this request.")

    cleaned_notes = (work_notes or "").strip()
    if not cleaned_notes:
        raise ValidationError("Work notes are required to resolve a request.")

    now = timezone.now()
    work_order.work_notes = cleaned_notes
    work_order.completed_at = now
    work_order.save(update_fields=["work_notes", "completed_at"])

    locked.status = ServiceRequest.Status.RESOLVED
    locked.resolved_at = now
    locked.resolution_summary = (resolution_summary or "").strip() or cleaned_notes
    locked.full_clean()
    locked.save(update_fields=["status", "resolved_at", "resolution_summary", "updated_at"])
    return locked