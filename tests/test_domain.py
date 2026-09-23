"""
Academic Domain model tests — AcademicYear, Semester, CourseOffering, Group, Schedule, SessionOccurrence.
"""

import pytest
from datetime import date, time
from django.db import IntegrityError

from apps.attendance.models import SessionOccurrence, SessionOccurrenceStatus
from tests.factories import (
    OrganizationFactory, AcademicYearFactory, SemesterFactory, CourseFactory,
    CourseOfferingFactory, DoctorFactory, TeachingAssistantFactory, GroupFactory,
    ScheduleFactory, SessionOccurrenceFactory,
)


@pytest.mark.django_db
class TestAcademicDomain:
    def test_academic_year_uniqueness(self):
        org = OrganizationFactory()
        AcademicYearFactory(organization=org, name='2026/2027')
        with pytest.raises(IntegrityError):
            AcademicYearFactory(organization=org, name='2026/2027')

    def test_semester_uniqueness(self):
        year = AcademicYearFactory()
        SemesterFactory(academic_year=year, name='Fall')
        with pytest.raises(IntegrityError):
            SemesterFactory(academic_year=year, name='Fall')

    def test_course_offering_creation(self):
        doctor = DoctorFactory()
        offering = CourseOfferingFactory(doctor=doctor)
        assert offering.status == 'ACTIVE'
        assert offering.doctor == doctor

    def test_group_creation_and_ta_assignment(self):
        ta = TeachingAssistantFactory()
        group = GroupFactory(teaching_assistant=ta)
        assert group.teaching_assistant == ta

    def test_session_occurrence_uniqueness(self):
        schedule = ScheduleFactory()
        today = date.today()
        SessionOccurrenceFactory(schedule=schedule, scheduled_date=today)
        with pytest.raises(IntegrityError):
            SessionOccurrenceFactory(schedule=schedule, scheduled_date=today)
