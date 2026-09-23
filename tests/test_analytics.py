"""
Analytics Reporting tests for Doctor, TA, Org Admin, and Superadmin.
"""

import pytest
from rest_framework.test import APIClient
from apps.accounts.models import Role, User

from tests.factories import (
    OrganizationFactory, AdminUserFactory, DoctorUserFactory, TAUserFactory,
    DoctorFactory, TeachingAssistantFactory, CourseOfferingFactory, GroupFactory,
)


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestAnalytics:
    def test_doctor_analytics(self, client):
        org = OrganizationFactory()
        doc_user = DoctorUserFactory(organization=org)
        doc = DoctorFactory(user=doc_user, organization=org)
        CourseOfferingFactory(doctor=doc)

        client.force_authenticate(user=doc_user)
        res = client.get('/api/v1/analytics/doctor/')
        assert res.status_code == 200
        assert 'overall_metrics' in res.data
        assert 'course_offerings' in res.data

    def test_ta_analytics(self, client):
        org = OrganizationFactory()
        ta_user = TAUserFactory(organization=org)
        ta = TeachingAssistantFactory(user=ta_user, organization=org)
        offering = CourseOfferingFactory(course__organization=org)
        GroupFactory(course_offering=offering, teaching_assistant=ta)

        client.force_authenticate(user=ta_user)
        res = client.get('/api/v1/analytics/ta/')
        assert res.status_code == 200
        assert 'overall_metrics' in res.data
        assert 'assigned_groups' in res.data

    def test_admin_analytics(self, client):
        org = OrganizationFactory()
        admin = AdminUserFactory(organization=org)

        client.force_authenticate(user=admin)
        res = client.get('/api/v1/analytics/admin/')
        assert res.status_code == 200
        assert 'organization_counts' in res.data
        assert 'metrics' in res.data

    def test_superadmin_analytics(self, client):
        superadmin = User.objects.create_user(
            email='superadmin@example.com',
            password='testpass123',
            first_name='Super',
            last_name='Admin',
            role=Role.SUPERADMIN,
            is_staff=True,
            is_superuser=True,
        )

        client.force_authenticate(user=superadmin)
        res = client.get('/api/v1/analytics/superadmin/')
        assert res.status_code == 200
        assert 'platform_metrics' in res.data
        assert 'organizations' in res.data
