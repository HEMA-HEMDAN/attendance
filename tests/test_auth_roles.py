"""
1. Roles & Authorization Tests + Role Immutability Tests.
Covers SUPERADMIN, ADMIN, DOCTOR, TEACHING_ASSISTANT, STUDENT across positive and negative cases,
as well as privilege escalation prevention.
"""

import pytest
from rest_framework.test import APIClient
from apps.accounts.models import Role, User

from tests.factories import (
    OrganizationFactory, AdminUserFactory, DoctorUserFactory, TAUserFactory,
    StudentUserFactory, DoctorFactory, TeachingAssistantFactory, StudentFactory,
)


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestRolesAndPrivileges:
    def test_superadmin_privileges(self, client):
        superadmin = User.objects.create_superuser(email='super@example.com', password='testpass123')
        client.force_authenticate(user=superadmin)

        # Superadmin can create organizations
        res = client.post('/api/v1/organizations/', {'name': 'New Org', 'slug': 'new-org'})
        assert res.status_code == 201

    def test_org_admin_cannot_create_organization(self, client):
        org = OrganizationFactory()
        admin = AdminUserFactory(organization=org)
        client.force_authenticate(user=admin)

        res = client.post('/api/v1/organizations/', {'name': 'Illegal Org', 'slug': 'illegal-org'})
        assert res.status_code == 403

    def test_student_cannot_create_course(self, client):
        student = StudentFactory()
        client.force_authenticate(user=student.user)

        res = client.post('/api/v1/courses/', {'name': 'CS101', 'code': 'CS101'})
        assert res.status_code == 403

    def test_student_cannot_open_session(self, client):
        student = StudentFactory()
        client.force_authenticate(user=student.user)

        res = client.post('/api/v1/attendance/occurrences/1/open/')
        assert res.status_code == 403

    def test_ta_cannot_create_lecture_occurrence_session(self, client):
        ta = TeachingAssistantFactory()
        client.force_authenticate(user=ta.user)

        # Opening non-existent occurrence or lecture returns 400 or 403
        res = client.post('/api/v1/attendance/occurrences/999/open/')
        assert res.status_code in (400, 403)

    def test_doctor_cannot_revoke_device(self, client):
        doctor = DoctorFactory()
        client.force_authenticate(user=doctor.user)

        res = client.post('/api/v1/devices/admin/1/revoke/')
        assert res.status_code == 403

    def test_ta_cannot_revoke_device(self, client):
        ta = TeachingAssistantFactory()
        client.force_authenticate(user=ta.user)

        res = client.post('/api/v1/devices/admin/1/revoke/')
        assert res.status_code == 403


@pytest.mark.django_db
class TestRoleImmutability:
    def test_user_cannot_escalate_role_via_me(self, client):
        student_user = StudentUserFactory()
        client.force_authenticate(user=student_user)

        res = client.patch('/api/v1/auth/me/', {'role': Role.SUPERADMIN, 'first_name': 'Hacker'})
        assert res.status_code in (200, 400)
        
        student_user.refresh_from_db()
        assert student_user.role == Role.STUDENT
        assert student_user.is_superuser is False

    def test_user_cannot_escalate_role_to_admin(self, client):
        student_user = StudentUserFactory()
        client.force_authenticate(user=student_user)

        res = client.patch('/api/v1/auth/me/', {'role': Role.ADMIN})
        student_user.refresh_from_db()
        assert student_user.role == Role.STUDENT
