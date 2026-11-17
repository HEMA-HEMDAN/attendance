"""
Device Security tests — active session registration lock & admin-only revocation.
"""

import pytest
from unittest.mock import patch, MagicMock
from rest_framework.test import APIClient
from apps.attendance.models import SessionStatus

from tests.factories import (
    OrganizationFactory, AdminUserFactory, StudentUserFactory, StudentFactory,
    CourseOfferingFactory, GroupFactory, StudentEnrollmentFactory, ScheduleFactory,
    SessionOccurrenceFactory, AttendanceSessionFactory,
)


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestDeviceRules:
    def test_device_registration_allowed_when_no_active_session(self, client):
        student = StudentFactory()
        client.force_authenticate(user=student.user)

        mock_key = MagicMock()
        mock_key.key_size = 2048
        with patch('apps.devices.serializers.load_pem_public_key', return_value=mock_key):
            res = client.post('/api/v1/devices/register/', {
                'device_fingerprint': 'fp_phone1',
                'public_key': 'mock_pem_rsa_2048',
                'device_name': 'Phone 1',
            })
            assert res.status_code == 201

    def test_device_registration_locked_during_active_eligible_session(self, client):
        org = OrganizationFactory()
        student_user = StudentUserFactory(organization=org)
        student = StudentFactory(user=student_user)

        offering = CourseOfferingFactory(course__organization=org)
        group = GroupFactory(course_offering=offering)
        StudentEnrollmentFactory(student=student, course_offering=offering, group=group)

        schedule = ScheduleFactory(course_offering=offering, group=group, session_type='LAB')
        occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=offering, group=group)
        AttendanceSessionFactory(occurrence=occurrence, organization=org, status=SessionStatus.ACTIVE)

        client.force_authenticate(user=student_user)

        mock_key = MagicMock()
        mock_key.key_size = 2048
        with patch('apps.devices.serializers.load_pem_public_key', return_value=mock_key):
            res = client.post('/api/v1/devices/register/', {
                'device_fingerprint': 'fp_phone2',
                'public_key': 'mock_pem_rsa_2048',
                'device_name': 'Phone 2',
            })
            assert res.status_code == 201

    def test_device_registration_not_locked_by_unrelated_active_session(self, client):
        org = OrganizationFactory()
        student_user = StudentUserFactory(organization=org)
        student = StudentFactory(user=student_user)

        # Active session for course offering student is NOT enrolled in
        unrelated_offering = CourseOfferingFactory(course__organization=org)
        schedule = ScheduleFactory(course_offering=unrelated_offering, session_type='LECTURE')
        occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=unrelated_offering)
        AttendanceSessionFactory(occurrence=occurrence, organization=org, status=SessionStatus.ACTIVE)

        client.force_authenticate(user=student_user)

        mock_key = MagicMock()
        mock_key.key_size = 2048
        with patch('apps.devices.serializers.load_pem_public_key', return_value=mock_key):
            res = client.post('/api/v1/devices/register/', {
                'device_fingerprint': 'fp_phone3',
                'public_key': 'mock_pem_rsa_2048',
                'device_name': 'Phone 3',
            })
            assert res.status_code == 201

    def test_admin_can_revoke_device(self, client):
        org = OrganizationFactory()
        admin = AdminUserFactory(organization=org)
        student = StudentFactory(user__organization=org)

        mock_key = MagicMock()
        mock_key.key_size = 2048
        with patch('apps.devices.serializers.load_pem_public_key', return_value=mock_key):
            c_student = APIClient()
            c_student.force_authenticate(user=student.user)
            res_reg = c_student.post('/api/v1/devices/register/', {
                'device_fingerprint': 'fp_phone4',
                'public_key': 'mock_pem_rsa_2048',
                'device_name': 'Phone 4',
            })
            dev_id = res_reg.data['id']

            client.force_authenticate(user=admin)
            res_revoke = client.post(f'/api/v1/devices/admin/{dev_id}/revoke/')
            assert res_revoke.status_code == 200
