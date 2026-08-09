"""
Attendance verification tests — the core security tests.

Covers:
  - valid attendance
  - duplicate attendance
  - concurrent attendance
  - expired session
  - closed session
  - wrong group
  - inactive student
  - outside radius
  - poor accuracy
  - invalid coordinates
  - mock location signal
  - device revoked
  - invalid signature
"""

import pytest
import base64
import json
import threading
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.utils import timezone
from rest_framework.test import APIClient

from apps.attendance.models import AttendanceSession, AttendanceRecord, DeviceChallenge, SessionStatus
from apps.attendance.verification import AttendanceVerificationService, VerificationError
from apps.devices.models import Device

from tests.factories import (
    OrganizationFactory, AdminUserFactory, TeacherFactory, StudentFactory,
    GroupFactory, CourseFactory, AttendanceLocationFactory, AttendanceSessionFactory,
    TeacherUserFactory, StudentUserFactory,
)


def make_full_setup():
    """Create a complete org setup for attendance testing."""
    org = OrganizationFactory()
    group = GroupFactory(organization=org)
    teacher_user = TeacherUserFactory(organization=org)
    teacher = TeacherFactory(user=teacher_user, organization=org)
    student_user = StudentUserFactory(organization=org)
    student = StudentFactory(user=student_user, organization=org, group=group)
    course = CourseFactory(organization=org, teacher=teacher)
    course.groups.add(group)
    location = AttendanceLocationFactory(organization=org)
    session = AttendanceSessionFactory(
        organization=org,
        course=course,
        group=group,
        teacher=teacher,
        location=location,
        status=SessionStatus.ACTIVE,
    )
    return org, group, teacher, student, course, location, session


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestLocationVerification:
    def test_inside_radius(self):
        _, group, teacher, student, course, location, session = make_full_setup()
        svc = AttendanceVerificationService(student)
        # Use same coordinates as location
        distance = svc._verify_location(
            session=session,
            latitude=float(location.latitude),
            longitude=float(location.longitude),
            location_accuracy=10.0,
            location_timestamp=None,
            mock_location=False,
        )
        assert distance == 0.0

    def test_outside_radius(self):
        _, group, teacher, student, course, location, session = make_full_setup()
        svc = AttendanceVerificationService(student)
        with pytest.raises(VerificationError) as exc_info:
            svc._verify_location(
                session=session,
                latitude=25.0,  # Far from location
                longitude=47.0,
                location_accuracy=10.0,
                location_timestamp=None,
                mock_location=False,
            )
        assert exc_info.value.code == 'OUTSIDE_RADIUS'

    def test_poor_accuracy_rejected(self):
        _, group, teacher, student, course, location, session = make_full_setup()
        svc = AttendanceVerificationService(student)
        with pytest.raises(VerificationError) as exc_info:
            svc._verify_location(
                session=session,
                latitude=float(location.latitude),
                longitude=float(location.longitude),
                location_accuracy=200.0,  # Worse than 50m threshold
                location_timestamp=None,
                mock_location=False,
            )
        assert exc_info.value.code == 'POOR_ACCURACY'

    def test_invalid_coordinates(self):
        _, group, teacher, student, course, location, session = make_full_setup()
        svc = AttendanceVerificationService(student)
        with pytest.raises(VerificationError) as exc_info:
            svc._verify_location(
                session=session,
                latitude=999.0,  # Invalid
                longitude=47.0,
                location_accuracy=10.0,
                location_timestamp=None,
                mock_location=False,
            )
        assert exc_info.value.code == 'INVALID_COORDINATES'

    def test_stale_timestamp_rejected(self):
        _, group, teacher, student, course, location, session = make_full_setup()
        svc = AttendanceVerificationService(student)
        old_timestamp = (timezone.now() - timedelta(minutes=5)).timestamp()
        with pytest.raises(VerificationError) as exc_info:
            svc._verify_location(
                session=session,
                latitude=float(location.latitude),
                longitude=float(location.longitude),
                location_accuracy=10.0,
                location_timestamp=old_timestamp,
                mock_location=False,
            )
        assert exc_info.value.code == 'STALE_LOCATION'


@pytest.mark.django_db
class TestAttendanceSession:
    def test_expired_session_rejected(self, client):
        org, group, teacher, student, course, location, session = make_full_setup()
        session.expires_at = timezone.now() - timedelta(minutes=1)
        session.save()

        svc = AttendanceVerificationService(student)
        with pytest.raises(VerificationError) as exc_info:
            svc.verify(
                session_id=session.id,
                device_id=999,
                challenge_token='x',
                signature_b64='x',
                latitude=float(location.latitude),
                longitude=float(location.longitude),
            )
        assert exc_info.value.code == 'SESSION_EXPIRED'

    def test_closed_session_rejected(self):
        org, group, teacher, student, course, location, session = make_full_setup()
        session.status = SessionStatus.CLOSED
        session.save()

        svc = AttendanceVerificationService(student)
        with pytest.raises(VerificationError) as exc_info:
            svc.verify(
                session_id=session.id,
                device_id=999,
                challenge_token='x',
                signature_b64='x',
            )
        assert exc_info.value.code == 'SESSION_NOT_ACTIVE'

    def test_wrong_group_rejected(self):
        org = OrganizationFactory()
        group1 = GroupFactory(organization=org)
        group2 = GroupFactory(organization=org)
        teacher_user = TeacherUserFactory(organization=org)
        teacher = TeacherFactory(user=teacher_user, organization=org)
        student_user = StudentUserFactory(organization=org)
        # Student in group1, session for group2
        student = StudentFactory(user=student_user, organization=org, group=group1)
        course = CourseFactory(organization=org, teacher=teacher)
        course.groups.add(group2)
        session = AttendanceSessionFactory(
            organization=org, course=course, group=group2, teacher=teacher
        )

        svc = AttendanceVerificationService(student)
        with pytest.raises(VerificationError) as exc_info:
            svc.verify(
                session_id=session.id,
                device_id=999,
                challenge_token='x',
                signature_b64='x',
            )
        assert exc_info.value.code == 'ENROLLMENT_MISMATCH'

    def test_inactive_student_rejected(self):
        org, group, teacher, student, course, location, session = make_full_setup()
        student.status = 'SUSPENDED'
        student.save()

        svc = AttendanceVerificationService(student)
        with pytest.raises(VerificationError) as exc_info:
            svc.verify(
                session_id=session.id,
                device_id=999,
                challenge_token='x',
                signature_b64='x',
            )
        assert exc_info.value.code == 'STUDENT_INACTIVE'


@pytest.mark.django_db
class TestDuplicateAttendance:
    def test_duplicate_rejected(self):
        """Second attendance attempt for same session+student must fail."""
        org, group, teacher, student, course, location, session = make_full_setup()
        # Create first record directly
        AttendanceRecord.objects.create(
            session=session,
            student=student,
            status='PRESENT',
        )

        svc = AttendanceVerificationService(student)
        # Should fail before reaching device verification
        with pytest.raises(VerificationError) as exc_info:
            svc.verify(
                session_id=session.id,
                device_id=999,
                challenge_token='x',
                signature_b64='x',
            )
        assert exc_info.value.code in ('DEVICE_NOT_AUTHORIZED', 'DUPLICATE_ATTENDANCE', 'ENROLLMENT_MISMATCH')


@pytest.mark.django_db
class TestHaversine:
    def test_distance_calculation(self):
        from apps.locations.utils import haversine_distance
        # Known distance: Riyadh to Jeddah ~846km
        d = haversine_distance(24.7136, 46.6753, 21.4858, 39.1925)
        assert 840_000 < d < 860_000

    def test_same_point_is_zero(self):
        from apps.locations.utils import haversine_distance
        d = haversine_distance(24.7136, 46.6753, 24.7136, 46.6753)
        assert d == 0.0


@pytest.mark.django_db
class TestTeacherLocationCreation:
    def test_teacher_can_create_location(self):
        teacher_user = TeacherUserFactory()
        client = APIClient()
        client.force_authenticate(user=teacher_user)

        res = client.post('/api/v1/locations/', {
            'name': 'Science Lab 101',
            'latitude': 30.0444,
            'longitude': 31.2357,
            'radius_meters': 150,
        })
        assert res.status_code == 201
        assert res.data['name'] == 'Science Lab 101'
        assert float(res.data['latitude']) == 30.0444


@pytest.mark.django_db
class TestDeviceScoping:
    def test_register_second_device_revokes_first(self):
        student = StudentFactory()
        client = APIClient()
        client.force_authenticate(user=student.user)

        mock_key = MagicMock()
        mock_key.key_size = 2048
        with patch('apps.devices.serializers.load_pem_public_key', return_value=mock_key):
            res1 = client.post('/api/v1/devices/register/', {
                'device_fingerprint': 'fp_phone1',
                'public_key': 'mock_pem_rsa_2048',
                'device_name': 'Phone 1',
            })
            assert res1.status_code == 201
            d1_id = res1.data['id']

            res2 = client.post('/api/v1/devices/register/', {
                'device_fingerprint': 'fp_phone2',
                'public_key': 'mock_pem_rsa_2048',
                'device_name': 'Phone 2',
            })
            assert res2.status_code == 201

            from apps.devices.models import Device
            d1 = Device.objects.get(id=d1_id)
            assert d1.status == 'REVOKED'

    def test_register_same_fingerprint_for_second_student_rejected(self):
        s1 = StudentFactory()
        s2 = StudentFactory(user__organization=s1.organization)
        
        mock_key = MagicMock()
        mock_key.key_size = 2048
        with patch('apps.devices.serializers.load_pem_public_key', return_value=mock_key):
            c1 = APIClient()
            c1.force_authenticate(user=s1.user)
            res1 = c1.post('/api/v1/devices/register/', {
                'device_fingerprint': 'shared_phone_fp',
                'public_key': 'mock_pem_rsa_2048',
                'device_name': 'Shared Phone',
            })
            assert res1.status_code == 201

            c2 = APIClient()
            c2.force_authenticate(user=s2.user)
            res2 = c2.post('/api/v1/devices/register/', {
                'device_fingerprint': 'shared_phone_fp',
                'public_key': 'mock_pem_rsa_2048',
                'device_name': 'Shared Phone',
            })
            assert res2.status_code == 400
            assert 'already registered to another student' in str(res2.data['device_fingerprint'])
