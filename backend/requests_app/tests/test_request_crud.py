from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import Category, ServiceRequest, WorkOrder
from .services import service_request_assign, service_request_resolve

User = get_user_model()


class PartMAssignmentAndResolutionTests(TestCase):
    def setUp(self):
        self.requester = User.objects.create_user(
            username="student_req", password="password123", is_staff=False
        )
        self.staff_user = User.objects.create_user(
            username="admin_staff", password="password123", is_staff=True
        )
        self.tech_user = User.objects.create_user(
            username="tech_staff", password="password123", is_staff=True
        )
        self.category = Category.objects.create(name="ICT Support")
        self.item = ServiceRequest.objects.create(
            requester=self.requester,
            category=self.category,
            title="Router offline in Lab 3",
            description="No internet connectivity on lab desktops.",
            location="Lab 3",
        )

    def test_non_staff_assignment_returns_403_and_creates_no_work_order(self):
        self.client.force_login(self.requester)
        url = reverse("requests:assign", kwargs={"request_id": self.item.id})
        response = self.client.post(url, {"technician": self.tech_user.id})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(WorkOrder.objects.count(), 0)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ServiceRequest.Status.OPEN)

    def test_staff_assignment_creates_one_work_order_and_sets_assigned(self):
        self.client.force_login(self.staff_user)
        url = reverse("requests:assign", kwargs={"request_id": self.item.id})
        response = self.client.post(url, {"technician": self.tech_user.id})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(WorkOrder.objects.count(), 1)

        work_order = WorkOrder.objects.get(service_request=self.item)
        self.assertEqual(work_order.technician, self.tech_user)

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ServiceRequest.Status.ASSIGNED)

    def test_resolution_without_assignment_leaves_request_unchanged(self):
        with self.assertRaises(ValidationError):
            service_request_resolve(
                item=self.item,
                actor=self.staff_user,
                work_notes="Attempted resolution without assignment.",
            )

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ServiceRequest.Status.OPEN)
        self.assertIsNone(self.item.resolved_at)

    def test_assigned_technician_resolution_changes_both_models(self):
        service_request_assign(
            item=self.item,
            actor=self.staff_user,
            technician=self.tech_user,
        )

        self.client.force_login(self.tech_user)
        url = reverse("requests:resolve", kwargs={"request_id": self.item.id})
        response = self.client.post(
            url,
            {"work_notes": "Replaced faulty Ethernet switch port and verified uplink."},
        )

        self.assertEqual(response.status_code, 302)

        self.item.refresh_from_db()
        work_order = WorkOrder.objects.get(service_request=self.item)

        self.assertEqual(self.item.status, ServiceRequest.Status.RESOLVED)
        self.assertIsNotNone(self.item.resolved_at)
        self.assertEqual(
            work_order.work_notes,
            "Replaced faulty Ethernet switch port and verified uplink.",
        )
        self.assertIsNotNone(work_order.completed_at)

    def test_filtered_pagination_preserves_q_and_status(self):
        for i in range(12):
            ServiceRequest.objects.create(
                requester=self.requester,
                category=self.category,
                title=f"Network Switch Fault #{i + 1}",
                description="Switch port flapping.",
                location="Lab 1",
                status=ServiceRequest.Status.OPEN,
            )

        self.client.force_login(self.requester)
        url = reverse("requests:list")
        response = self.client.get(url, {"q": "Switch", "status": "open", "page": 2})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].number, 2)
        self.assertEqual(response.context["query"], "Switch")
        self.assertEqual(response.context["status"], "open")
        self.assertContains(response, "q=Switch")
        self.assertContains(response, "status=open")