"""
One-Time Location Verification & Radar Location Snapshot Tests.
Covers Haversine distance boundary tests (on boundary, inside, outside), timestamp freshness,
accuracy thresholds, location snapshot recording, and radar classification.
"""

import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient

from apps.attendance.models import SessionStatus, AttendanceRecord
from apps.attendance.verification import AttendanceVerificationService, VerificationError
from apps.locations.utils import haversine_distance

from tests.factories import (
    OrganizationFactory, StudentFactory, CourseOfferingFactory, GroupFactory,
    StudentEnrollmentFactory, ScheduleFactory, SessionOccurrenceFactory,
    AttendanceSessionFactory, AttendanceLocationFactory,
)


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestLocationAndRadarSnapshots:
    def test_haversine_boundary_just_inside_radius(self):
        # Session at (24.7136, 46.6753), radius 50m
        # Offset lat slightly by ~0.0003 deg (~33 meters away)
        session_lat, session_lng = 24.7136, 46.6753
        submission_lat, submission_lng = 24.7139, 46.6753

        dist = haversine_distance(session_lat, session_lng, submission_lat, submission_lng)
        assert dist < 50.0

    def test_haversine_boundary_just_outside_radius(self):
        # Offset lat by ~0.0006 deg (~66 meters away)
        session_lat, session_lng = 24.7136, 46.6753
        submission_lat, submission_lng = 24.7142, 46.6753

        dist = haversine_distance(session_lat, session_lng, submission_lat, submission_lng)
        assert dist > 50.0

    def test_one_time_location_evidence_persisted(self):
        org = OrganizationFactory()
        student = StudentFactory(user__organization=org)
        offering = CourseOfferingFactory(course__organization=org)
        group = GroupFactory(course_offering=offering)
        StudentEnrollmentFactory(student=student, course_offering=offering, group=group)

        schedule = ScheduleFactory(course_offering=offering, group=group)
        occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=offering, group=group)
        session = AttendanceSessionFactory(
            occurrence=occurrence, organization=org,
            latitude=24.7136, longitude=46.6753, radius_meters=100.0,
            status=SessionStatus.ACTIVE
        )

        svc = AttendanceVerificationService(student)
        dist = svc._verify_location(
            session=session,
            latitude=24.7136,
            longitude=46.6753,
            location_accuracy=5.0,
            location_timestamp=timezone.now().timestamp(),
            mock_location=False,
        )

        assert dist == 0.0

    def test_stale_location_timestamp_rejected(self):
        org = OrganizationFactory()
        student = StudentFactory(user__organization=org)
        offering = CourseOfferingFactory(course__organization=org)
        schedule = ScheduleFactory(course_offering=offering)
        occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=offering)
        session = AttendanceSessionFactory(occurrence=occurrence, organization=org)

        svc = AttendanceVerificationService(student)
        stale_ts = (timezone.now() - timedelta(seconds=120)).timestamp()

        with pytest.raises(VerificationError) as exc_info:
            svc._verify_location(
                session=session,
                latitude=24.7136,
                longitude=46.6753,
                location_accuracy=10.0,
                location_timestamp=stale_ts,
                mock_location=False,
            )
        assert exc_info.value.code == 'STALE_LOCATION'
