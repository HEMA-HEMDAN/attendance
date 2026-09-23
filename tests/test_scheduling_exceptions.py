"""
Scheduling & Exceptions Tests + Timezone Boundary Tests.
Covers Schedule date boundaries, ScheduleException overrides, and Organization timezone calculations.
"""

import pytest
import zoneinfo
from datetime import date, time, datetime
from django.utils import timezone
from rest_framework.test import APIClient

from apps.attendance.services import get_org_now_and_today, sync_today_occurrences
from apps.courses.models import ExceptionType, ScheduleException

from tests.factories import (
    OrganizationFactory, AcademicYearFactory, SemesterFactory, CourseFactory,
    CourseOfferingFactory, ScheduleFactory,
)


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestSchedulingAndExceptions:
    def test_organization_timezone_today_calculation(self):
        org_cairo = OrganizationFactory(timezone='Africa/Cairo')
        org_ny = OrganizationFactory(timezone='America/New_York')

        org_now_cairo, today_cairo, weekday_cairo = get_org_now_and_today(org_cairo)
        org_now_ny, today_ny, weekday_ny = get_org_now_and_today(org_ny)

        assert today_cairo is not None
        assert today_ny is not None

    def test_schedule_effective_date_boundaries(self):
        org = OrganizationFactory(timezone='Africa/Cairo')
        year = AcademicYearFactory(organization=org, start_date=date(2026, 9, 1), end_date=date(2027, 6, 30))
        sem = SemesterFactory(academic_year=year, start_date=date(2026, 9, 1), end_date=date(2027, 12, 31))
        offering = CourseOfferingFactory(course__organization=org, academic_year=year, semester=sem)

        today_date = date.today()
        weekday_int = today_date.weekday()

        # Schedule inactive by effective_until in past
        sched_past = ScheduleFactory(
            course_offering=offering,
            day_of_week=weekday_int,
            effective_from=date(2020, 1, 1),
            effective_until=date(2020, 12, 31),
        )

        occurrences = sync_today_occurrences(org)
        occ_schedule_ids = [occ.schedule_id for occ in occurrences]
        assert sched_past.id not in occ_schedule_ids

    def test_schedule_cancelled_exception(self):
        org = OrganizationFactory(timezone='Africa/Cairo')
        year = AcademicYearFactory(organization=org, start_date=date(2026, 1, 1), end_date=date(2030, 12, 31))
        sem = SemesterFactory(academic_year=year, start_date=date(2026, 1, 1), end_date=date(2030, 12, 31))
        offering = CourseOfferingFactory(course__organization=org, academic_year=year, semester=sem)

        today_date = date.today()
        weekday_int = today_date.weekday()

        sched = ScheduleFactory(course_offering=offering, day_of_week=weekday_int)
        ScheduleException.objects.create(
            schedule=sched,
            date=today_date,
            exception_type=ExceptionType.CANCELLED,
            reason='Holiday',
        )

        occurrences = sync_today_occurrences(org)
        occ_schedule_ids = [occ.schedule_id for occ in occurrences]
        assert sched.id not in occ_schedule_ids

    def test_schedule_moved_time_exception(self):
        org = OrganizationFactory(timezone='Africa/Cairo')
        year = AcademicYearFactory(organization=org, start_date=date(2026, 1, 1), end_date=date(2030, 12, 31))
        sem = SemesterFactory(academic_year=year, start_date=date(2026, 1, 1), end_date=date(2030, 12, 31))
        offering = CourseOfferingFactory(course__organization=org, academic_year=year, semester=sem)

        today_date = date.today()
        weekday_int = today_date.weekday()

        sched = ScheduleFactory(course_offering=offering, day_of_week=weekday_int, start_time=time(10, 0), end_time=time(12, 0))
        ScheduleException.objects.create(
            schedule=sched,
            date=today_date,
            exception_type=ExceptionType.MOVED,
            new_start_time=time(14, 0),
            new_end_time=time(16, 0),
            reason='Moved to afternoon',
        )

        occurrences = sync_today_occurrences(org)
        target_occ = next((occ for occ in occurrences if occ.schedule_id == sched.id), None)
        assert target_occ is not None
        assert target_occ.starts_at.hour == 14
