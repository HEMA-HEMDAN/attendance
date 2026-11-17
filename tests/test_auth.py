"""
Authentication tests — login, logout, role enforcement, organization isolation.
"""

import pytest
from rest_framework.test import APIClient
from tests.factories import (
    OrganizationFactory, AdminUserFactory, DoctorUserFactory, StudentUserFactory,
    StudentFactory,
)


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def org():
    return OrganizationFactory()


@pytest.fixture
def admin_user(org):
    return AdminUserFactory(organization=org)


@pytest.fixture
def doctor_user(org):
    return DoctorUserFactory(organization=org)


@pytest.fixture
def student_user(org):
    return StudentUserFactory(organization=org)


@pytest.mark.django_db
class TestLogin:
    def test_valid_login(self, client, admin_user):
        response = client.post('/api/v1/auth/login/', {
            'email': admin_user.email,
            'password': 'testpass123',
        })
        assert response.status_code == 200
        assert 'access' in response.data
        assert 'refresh' in response.data
        assert response.data['user']['role'] == 'ADMIN'

    def test_invalid_password(self, client, admin_user):
        response = client.post('/api/v1/auth/login/', {
            'email': admin_user.email,
            'password': 'wrongpassword',
        })
        assert response.status_code == 401

    def test_inactive_user(self, client, org):
        user = AdminUserFactory(organization=org, is_active=False)
        response = client.post('/api/v1/auth/login/', {
            'email': user.email,
            'password': 'testpass123',
        })
        assert response.status_code == 401

    def test_token_includes_role(self, client, doctor_user):
        response = client.post('/api/v1/auth/login/', {
            'email': doctor_user.email,
            'password': 'testpass123',
        })
        assert response.status_code == 200
        assert response.data['user']['role'] == 'DOCTOR'

    def test_me_endpoint(self, client, admin_user):
        client.force_authenticate(user=admin_user)
        response = client.get('/api/v1/auth/me/')
        assert response.status_code == 200
        assert response.data['email'] == admin_user.email


@pytest.mark.django_db
class TestOrganizationIsolation:
    def test_admin_cannot_see_other_org_students(self, client):
        org1 = OrganizationFactory()
        org2 = OrganizationFactory()
        admin1 = AdminUserFactory(organization=org1)
        student_in_org2 = StudentFactory(organization=org2)

        client.force_authenticate(user=admin1)
        response = client.get('/api/v1/students/')
        assert response.status_code == 200
        student_ids = [s['student_id'] for s in response.data['results']]
        assert student_in_org2.student_id not in student_ids

    def test_student_cannot_access_admin_endpoints(self, client, student_user, org):
        StudentFactory(user=student_user, organization=org)
        client.force_authenticate(user=student_user)
        response = client.get('/api/v1/students/')
        assert response.status_code == 403

    def test_doctor_cannot_create_students(self, client, doctor_user):
        client.force_authenticate(user=doctor_user)
        response = client.post('/api/v1/students/', {
            'student_id': 'TEST001',
            'first_name': 'Test',
            'last_name': 'Student',
            'email': 'test@example.com',
        })
        assert response.status_code == 403
