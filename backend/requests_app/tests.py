from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from .models import Category, ServiceRequest

User = get_user_model()


class ServiceRequestExtensionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="student1", password="password123")
        self.category = Category.objects.create(name="Electrical")

    def test_query_requests_due_before_chosen_time(self):
        now = timezone.now()
        early_req = ServiceRequest.objects.create(
            requester=self.user,
            category=self.category,
            title="Urgent Breaker Issue",
            description="Main breaker tripping.",
            location="Lab 1",
            due_at=now + timedelta(hours=2),
        )
        later_req = ServiceRequest.objects.create(
            requester=self.user,
            category=self.category,
            title="Routine Socket Check",
            description="Check wall outlets.",
            location="Lab 2",
            due_at=now + timedelta(days=3),
        )

        due_soon = ServiceRequest.objects.filter(due_at__lt=now + timedelta(hours=12))
        self.assertIn(early_req, due_soon)
        self.assertNotIn(later_req, due_soon)

    def test_resolved_or_closed_requires_resolved_at_and_summary(self):
        req = ServiceRequest(
            requester=self.user,
            category=self.category,
            title="Faulty Projector",
            description="No HDMI signal.",
            location="Lecture Hall A",
            status=ServiceRequest.Status.RESOLVED,
            resolved_at=None,
            resolution_summary="   ",
        )

        with self.assertRaises(ValidationError) as ctx:
            req.full_clean()

        self.assertIn("resolved_at", ctx.exception.message_dict)
        self.assertIn("resolution_summary", ctx.exception.message_dict)

    def test_valid_closed_request_passes_full_clean(self):
        req = ServiceRequest(
            requester=self.user,
            category=self.category,
            title="Faulty Projector",
            description="No HDMI signal.",
            location="Lecture Hall A",
            status=ServiceRequest.Status.CLOSED,
            resolved_at=timezone.now(),
            resolution_summary="Replaced damaged HDMI cable and tested display.",
        )
        req.full_clean()