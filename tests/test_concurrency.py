"""
Concurrency & Race Condition Invariant Tests.
Tests database-level unique constraints and atomic session handling under concurrent operations.
"""

import pytest
import threading
from django.db import IntegrityError, close_old_connections
from django.utils import timezone
from datetime import date
from rest_framework.test import APIClient

from apps.attendance.models import SessionOccurrence, SessionOccurrenceStatus, AttendanceSession, AttendanceRecord, SessionStatus
from apps.attendance.services import open_occurrence_session

from tests.factories import (
    OrganizationFactory, DoctorUserFactory, DoctorFactory, StudentUserFactory,
    StudentFactory, CourseOfferingFactory, GroupFactory, StudentEnrollmentFactory,
    ScheduleFactory, SessionOccurrenceFactory, AttendanceSessionFactory,
)


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestConcurrencyInvariants:
    def test_concurrent_session_occurrence_creation_uniqueness(self, transactional_db):
        schedule = ScheduleFactory()
        today_date = date.today()

        def create_occurrence(results, index):
            try:
                close_old_connections()
                occ, _ = SessionOccurrence.objects.get_or_create(
                    schedule=schedule,
                    scheduled_date=today_date,
                    defaults={
                        'course_offering': schedule.course_offering,
                        'group': schedule.group,
                        'starts_at': timezone.make_aware(
                            timezone.datetime.combine(
                                schedule.course_offering.academic_year.start_date,
                                timezone.datetime.min.time(),
                            )
                        ),
                        'ends_at': timezone.make_aware(
                            timezone.datetime.combine(
                                schedule.course_offering.academic_year.end_date,
                                timezone.datetime.min.time(),
                            )
                        ),
                        'session_type': schedule.session_type,
                        'status': SessionOccurrenceStatus.SCHEDULED,
                    }
                )
                results[index] = occ.id
            except Exception as e:
                results[index] = e
            finally:
                close_old_connections()

        threads = []
        results = [None, None]
        for i in range(2):
            t = threading.Thread(target=create_occurrence, args=(results, i))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert all(not isinstance(result, Exception) for result in results), results

        # Exactly one unique occurrence exists in DB
        occurrences = SessionOccurrence.objects.filter(schedule=schedule, scheduled_date=today_date)
        assert occurrences.count() == 1

    def test_duplicate_attendance_record_race_condition_prevented(self):
        org = OrganizationFactory()
        student_user = StudentUserFactory(organization=org)
        student = StudentFactory(user=student_user)

        offering = CourseOfferingFactory(course__organization=org)
        schedule = ScheduleFactory(course_offering=offering)
        occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=offering)
        session = AttendanceSessionFactory(occurrence=occurrence, organization=org, status=SessionStatus.ACTIVE)

        AttendanceRecord.objects.create(session=session, student=student, status='PRESENT')

        # Concurrent second creation attempt fails at DB level
        with pytest.raises(IntegrityError):
            AttendanceRecord.objects.create(session=session, student=student, status='PRESENT')
