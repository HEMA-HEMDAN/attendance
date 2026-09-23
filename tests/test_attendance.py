"""
Attendance verification & security tests for the refactored University Attendance backend.
"""

import pytest
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.attendance.models import AttendanceSession, AttendanceRecord, SessionStatus
from apps.attendance.verification import AttendanceVerificationService, VerificationError

from tests.factories import (
    OrganizationFactory, AdminUserFactory, DoctorFactory, TeachingAssistantFactory,
    StudentFactory, AcademicYearFactory, SemesterFactory, CourseFactory,
    CourseOfferingFactory, GroupFactory, StudentEnrollmentFactory, ScheduleFactory,
    SessionOccurrenceFactory, AttendanceSessionFactory, AttendanceLocationFactory,
)


def make_full_setup():
    """Create a complete org setup for attendance testing."""
    org = OrganizationFactory()
    doctor = DoctorFactory(user__organization=org)
    ta = TeachingAssistantFactory(user__organization=org)
    academic_year = AcademicYearFactory(organization=org)
    semester = SemesterFactory(academic_year=academic_year)
    course = CourseFactory(organization=org)
    offering = CourseOfferingFactory(course=course, academic_year=academic_year, semester=semester, doctor=doctor)
    group = GroupFactory(course_offering=offering, teaching_assistant=ta)
    student = StudentFactory(user__organization=org)
    StudentEnrollmentFactory(student=student, course_offering=offering, group=group)
    schedule = ScheduleFactory(course_offering=offering, group=group, session_type='LAB')
    occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=offering, group=group, session_type='LAB')
    location = AttendanceLocationFactory(organization=org)
    session = AttendanceSessionFactory(
        occurrence=occurrence,
        organization=org,
        opened_by=ta.user,
        latitude=float(location.latitude),
        longitude=float(location.longitude),
        status=SessionStatus.ACTIVE,
    )
    return org, group, doctor, ta, student, offering, location, session


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestLocationVerification:
    def test_inside_radius(self):
        _, group, doctor, ta, student, offering, location, session = make_full_setup()
        svc = AttendanceVerificationService(student)
        distance = svc._verify_location(
            session=session,
            latitude=float(location.latitude),
            longitude=float(location.longitude),
            location_accuracy=10.0,
            location_timestamp=timezone.now().timestamp(),
            mock_location=False,
        )
        assert distance == 0.0

    def test_outside_radius(self):
        _, group, doctor, ta, student, offering, location, session = make_full_setup()
        svc = AttendanceVerificationService(student)
        with pytest.raises(VerificationError) as exc_info:
            svc._verify_location(
                session=session,
                latitude=25.0,
                longitude=47.0,
                location_accuracy=10.0,
                location_timestamp=timezone.now().timestamp(),
                mock_location=False,
            )
        assert exc_info.value.code == 'OUTSIDE_RADIUS'

    def test_poor_accuracy_rejected(self):
        _, group, doctor, ta, student, offering, location, session = make_full_setup()
        svc = AttendanceVerificationService(student)
        with pytest.raises(VerificationError) as exc_info:
            svc._verify_location(
                session=session,
                latitude=float(location.latitude),
                longitude=float(location.longitude),
                location_accuracy=200.0,
                location_timestamp=timezone.now().timestamp(),
                mock_location=False,
            )
        assert exc_info.value.code == 'POOR_ACCURACY'

    def test_invalid_coordinates(self):
        _, group, doctor, ta, student, offering, location, session = make_full_setup()
        svc = AttendanceVerificationService(student)
        with pytest.raises(VerificationError) as exc_info:
            svc._verify_location(
                session=session,
                latitude=999.0,
                longitude=47.0,
                location_accuracy=10.0,
                location_timestamp=timezone.now().timestamp(),
                mock_location=False,
            )
        assert exc_info.value.code == 'INVALID_COORDINATES'

    def test_stale_timestamp_rejected(self):
        _, group, doctor, ta, student, offering, location, session = make_full_setup()
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
    def test_expired_session_rejected(self):
        org, group, doctor, ta, student, offering, location, session = make_full_setup()
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
        org, group, doctor, ta, student, offering, location, session = make_full_setup()
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
        offering = CourseOfferingFactory(course__organization=org)
        g1 = GroupFactory(course_offering=offering)
        g2 = GroupFactory(course_offering=offering)
        student = StudentFactory(user__organization=org)
        # Student enrolled in g1, session for g2
        StudentEnrollmentFactory(student=student, course_offering=offering, group=g1)
        schedule = ScheduleFactory(course_offering=offering, group=g2, session_type='LAB')
        occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=offering, group=g2)
        session = AttendanceSessionFactory(occurrence=occurrence, organization=org)

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
        org, group, doctor, ta, student, offering, location, session = make_full_setup()
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
        org, group, doctor, ta, student, offering, location, session = make_full_setup()
        AttendanceRecord.objects.create(
            session=session,
            student=student,
            status='PRESENT',
        )

        svc = AttendanceVerificationService(student)
        with pytest.raises(VerificationError) as exc_info:
            svc.verify(
                session_id=session.id,
                device_id=999,
                challenge_token='x',
                signature_b64='x',
            )
        assert exc_info.value.code in ('DEVICE_NOT_AUTHORIZED', 'DUPLICATE_ATTENDANCE', 'ENROLLMENT_MISMATCH')
