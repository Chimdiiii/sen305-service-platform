from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .forms import (
    AssignmentForm,
    CommentForm,
    ResolutionForm,
    ServiceRequestForm,
)
from .models import ServiceRequest
from .selectors import (
    service_request_filter,
    service_request_get,
    service_request_summary_counts,
)
from .services import (
    comment_create,
    service_request_assign,
    service_request_create,
    service_request_resolve,
    service_request_update,
)


@login_required
def request_list(request):
    status = request.GET.get("status", "").strip()
    query = request.GET.get("q", "").strip()

    queryset = service_request_filter(user=request.user, status=status, query=query)

    # Task 3: Reusable query string that retains q and status across page changes
    query_params = request.GET.copy()
    query_params.pop("page", None)
    preserved_query = query_params.urlencode()

    paginator = Paginator(queryset, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    # Task 4: Open, Assigned, and Resolved summary counts scoped to visible requests
    summary_counts = service_request_summary_counts(user=request.user)

    return render(
        request,
        "requests_app/request_list.html",
        {
            "page_obj": page_obj,
            "status": status,
            "query": query,
            "status_choices": ServiceRequest.Status.choices,
            "preserved_query": preserved_query,
            "summary_counts": summary_counts,
        },
    )


@login_required
def request_detail(request, request_id):
    try:
        item = service_request_get(user=request.user, request_id=request_id)
    except ServiceRequest.DoesNotExist as exc:
        raise Http404("Service request not found.") from exc

    work_order = getattr(item, "work_order", None)
    can_assign = request.user.is_staff
    can_resolve = bool(
        work_order
        and (request.user.is_staff or work_order.technician_id == request.user.id)
        and item.status not in {ServiceRequest.Status.RESOLVED, ServiceRequest.Status.CLOSED}
    )

    return render(
        request,
        "requests_app/request_detail.html",
        {
            "item": item,
            "work_order": work_order,
            "comments": item.comments.select_related("author").all(),
            "comment_form": CommentForm(),
            "assign_form": AssignmentForm() if can_assign else None,
            "resolve_form": ResolutionForm() if can_resolve else None,
            "can_assign": can_assign,
            "can_resolve": can_resolve,
        },
    )


@login_required
def request_create(request):
    if request.method == "POST":
        form = ServiceRequestForm(request.POST)
        if form.is_valid():
            try:
                item = service_request_create(
                    requester=request.user,
                    category=form.cleaned_data["category"],
                    title=form.cleaned_data["title"],
                    description=form.cleaned_data["description"],
                    location=form.cleaned_data["location"],
                    priority=form.cleaned_data["priority"],
                )
                messages.success(request, "Service request submitted.")
                return redirect("requests:detail", request_id=item.id)
            except ValidationError as exc:
                for msg in exc.messages:
                    messages.error(request, msg)
    else:
        form = ServiceRequestForm()

    return render(
        request,
        "requests_app/request_form.html",
        {"form": form, "mode": "create"},
    )


@login_required
def request_edit(request, request_id):
    try:
        item = service_request_get(user=request.user, request_id=request_id)
    except ServiceRequest.DoesNotExist as exc:
        raise Http404("Service request not found.") from exc

    if request.method == "POST":
        form = ServiceRequestForm(request.POST, instance=item)
        if form.is_valid():
            try:
                service_request_update(
                    item=item,
                    actor=request.user,
                    category=form.cleaned_data["category"],
                    title=form.cleaned_data["title"],
                    description=form.cleaned_data["description"],
                    location=form.cleaned_data["location"],
                    priority=form.cleaned_data["priority"],
                )
                messages.success(request, "Service request updated.")
                return redirect("requests:detail", request_id=item.id)
            except ValidationError as exc:
                for msg in exc.messages:
                    messages.error(request, msg)
    else:
        form = ServiceRequestForm(instance=item)

    return render(
        request,
        "requests_app/request_form.html",
        {"form": form, "item": item, "mode": "edit"},
    )


@login_required
@require_POST
def request_comment(request, request_id):
    try:
        item = service_request_get(user=request.user, request_id=request_id)
    except ServiceRequest.DoesNotExist as exc:
        raise Http404("Service request not found.") from exc

    form = CommentForm(request.POST)
    if form.is_valid():
        try:
            comment_create(
                item=item,
                author=request.user,
                body=form.cleaned_data["body"],
            )
            messages.success(request, "Comment added.")
        except ValidationError as exc:
            for msg in exc.messages:
                messages.error(request, msg)
    else:
        for errors in form.errors.values():
            for err in errors:
                messages.error(request, err)

    return redirect("requests:detail", request_id=item.id)


@login_required
@require_POST
def request_assign(request, request_id):
    if not request.user.is_staff:
        raise PermissionDenied("Only staff members can assign service requests.")

    try:
        item = service_request_get(user=request.user, request_id=request_id)
    except ServiceRequest.DoesNotExist as exc:
        raise Http404("Service request not found.") from exc

    form = AssignmentForm(request.POST)
    if form.is_valid():
        try:
            service_request_assign(
                item=item,
                actor=request.user,
                technician=form.cleaned_data["technician"],
            )
            messages.success(request, "Service request assigned.")
        except ValidationError as exc:
            for msg in exc.messages:
                messages.error(request, msg)
    else:
        for errors in form.errors.values():
            for err in errors:
                messages.error(request, err)

    return redirect("requests:detail", request_id=item.id)


@login_required
@require_POST
def request_resolve(request, request_id):
    # Fetch directly so an assigned technician can still resolve even if they weren't the original requester
    try:
        item = ServiceRequest.objects.select_related("work_order__technician").get(id=request_id)
    except ServiceRequest.DoesNotExist as exc:
        raise Http404("Service request not found.") from exc

    work_order = getattr(item, "work_order", None)
    is_assigned_tech = bool(work_order and work_order.technician_id == request.user.id)
    if not (request.user.is_staff or is_assigned_tech):
        raise PermissionDenied("Only staff or the assigned technician can resolve this request.")

    form = ResolutionForm(request.POST)
    if form.is_valid():
        try:
            service_request_resolve(
                item=item,
                actor=request.user,
                work_notes=form.cleaned_data["work_notes"],
                resolution_summary=form.cleaned_data.get("resolution_summary", ""),
            )
            messages.success(request, "Service request resolved.")
        except ValidationError as exc:
            for msg in exc.messages:
                messages.error(request, msg)
    else:
        for errors in form.errors.values():
            for err in errors:
                messages.error(request, err)

    return redirect("requests:detail", request_id=item.id)