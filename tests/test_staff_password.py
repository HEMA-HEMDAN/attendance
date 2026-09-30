"""
Tests for staff password change and reset routes (API & Web).
"""

import pytest
from rest_framework.test import APIClient
from django.test import Client
from tests.factories import (
    OrganizationFactory, AdminUserFactory, DoctorUserFactory, TAUserFactory,
    DoctorFactory,
)
from apps.staff.models import TeachingAssistant


@pytest.fixture
def api_client():
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
def doctor(doctor_user, org):
    return DoctorFactory(user=doctor_user, organization=org)


@pytest.fixture
def ta_user(org):
    return TAUserFactory(organization=org)


@pytest.fixture
def ta(ta_user, org):
    return TeachingAssistant.objects.create(user=ta_user, organization=org, department='CS')


@pytest.mark.django_db
class TestStaffPasswordAPI:
    def test_staff_self_change_password_success(self, api_client, doctor_user):
        api_client.force_authenticate(user=doctor_user)
        response = api_client.post('/api/v1/staff/change-password/', {
            'old_password': 'testpass123',
            'new_password': 'newsecretpassword123',
        })
        assert response.status_code == 200
        assert response.data['detail'] == 'Password successfully changed.'

        doctor_user.refresh_from_db()
        assert doctor_user.check_password('newsecretpassword123')

    def test_staff_self_change_password_wrong_old(self, api_client, doctor_user):
        api_client.force_authenticate(user=doctor_user)
        response = api_client.post('/api/v1/staff/change-password/', {
            'old_password': 'wrongoldpassword',
            'new_password': 'newsecretpassword123',
        })
        assert response.status_code == 400
        assert 'old_password' in response.data or 'non_field_errors' in response.data

    def test_admin_reset_doctor_password(self, api_client, admin_user, doctor):
        api_client.force_authenticate(user=admin_user)
        response = api_client.post(f'/api/v1/staff/doctors/{doctor.id}/change-password/', {
            'new_password': 'adminsetpassword123',
        })
        assert response.status_code == 200
        assert 'reset successfully' in response.data['detail']

        doctor.user.refresh_from_db()
        assert doctor.user.check_password('adminsetpassword123')

    def test_admin_reset_ta_password(self, api_client, admin_user, ta):
        api_client.force_authenticate(user=admin_user)
        response = api_client.post(f'/api/v1/staff/assistants/{ta.id}/change-password/', {
            'new_password': 'taadminsetpassword123',
        })
        assert response.status_code == 200
        assert 'reset successfully' in response.data['detail']

        ta.user.refresh_from_db()
        assert ta.user.check_password('taadminsetpassword123')

    def test_admin_cannot_reset_other_org_doctor(self, api_client, org):
        org2 = OrganizationFactory()
        admin1 = AdminUserFactory(organization=org)
        doctor2_user = DoctorUserFactory(organization=org2)
        doctor2 = DoctorFactory(user=doctor2_user, organization=org2)

        api_client.force_authenticate(user=admin1)
        response = api_client.post(f'/api/v1/staff/doctors/{doctor2.id}/change-password/', {
            'new_password': 'hackpassword123',
        })
        assert response.status_code == 404


@pytest.mark.django_db
class TestStaffPasswordWeb:
    def test_web_change_password_get(self, doctor_user):
        client = Client()
        client.force_login(doctor_user)
        response = client.get('/analytics/change-password/')
        assert response.status_code == 200
        assert 'Change Password' in response.content.decode()

    def test_web_change_password_post_success(self, doctor_user):
        client = Client()
        client.force_login(doctor_user)
        response = client.post('/analytics/change-password/', {
            'old_password': 'testpass123',
            'new_password': 'webnewpassword123',
            'confirm_password': 'webnewpassword123',
        })
        assert response.status_code == 200
        assert 'Your password has been changed successfully.' in response.content.decode()

        doctor_user.refresh_from_db()
        assert doctor_user.check_password('webnewpassword123')
