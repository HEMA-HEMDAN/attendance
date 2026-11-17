"""
Workflow & Role Authorization tests — Doctor today work, TA today work, Student today work,
occurrence session opening, session closing, NO REOPEN.
"""

import pytest
from datetime import date
from django.utils import timezone
from rest_framework.test import APIClient
from apps.attendance.models import SessionStatus

from tests.factories import (
    OrganizationFactory, DoctorUserFactory, TAUserFactory, StudentUserFactory,
    DoctorFactory, TeachingAssistantFactory, StudentFactory, AcademicYearFactory,
    SemesterFactory, CourseFactory, CourseOfferingFactory, GroupFactory,
    StudentEnrollmentFactory, ScheduleFactory, SessionOccurrenceFactory,
    AttendanceSessionFactory,
)


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestDoctorWorkflow:
    def test_doctor_today_work(self, client):
        org = OrganizationFactory()
        doctor_user = DoctorUserFactory(organization=org)
        doctor = DoctorFactory(user=doctor_user)

        year = AcademicYearFactory(organization=org)
        sem = SemesterFactory(academic_year=year)
        course = CourseFactory(organization=org)
        offering = CourseOfferingFactory(course=course, academic_year=year, semester=sem, doctor=doctor)

        today_weekday = date.today().weekday()
        ScheduleFactory(course_offering=offering, day_of_week=today_weekday, session_type='LECTURE')

        client.force_authenticate(user=doctor_user)
        res = client.get('/api/v1/attendance/today/')
        assert res.status_code == 200
        assert len(res.data) == 1
        assert res.data[0]['course_code'] == course.code
        assert res.data[0]['session_type'] == 'LECTURE'
        assert res.data[0]['can_open'] is True

    def test_doctor_can_open_lecture(self, client):
        org = OrganizationFactory()
        doctor_user = DoctorUserFactory(organization=org)
        doctor = DoctorFactory(user=doctor_user)

        course = CourseFactory(organization=org)
        offering = CourseOfferingFactory(course=course, doctor=doctor)
        schedule = ScheduleFactory(course_offering=offering, session_type='LECTURE')
        occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=offering, session_type='LECTURE')

        client.force_authenticate(user=doctor_user)
        loc_data = {
            'latitude': 30.0444,
            'longitude': 31.2357,
            'location_accuracy_meters': 10.0,
            'location_captured_at': timezone.now().isoformat(),
        }
        res = client.post(f'/api/v1/attendance/occurrences/{occurrence.id}/open/', loc_data, format='json')
        assert res.status_code == 201
        assert res.data['status'] == 'ACTIVE'

    def test_doctor_cannot_open_unowned_course_lecture(self, client):
        org = OrganizationFactory()
        doctor_user1 = DoctorUserFactory(organization=org)
        doctor1 = DoctorFactory(user=doctor_user1)
        doctor2 = DoctorFactory(user__organization=org)

        course = CourseFactory(organization=org)
        offering = CourseOfferingFactory(course=course, doctor=doctor2)
        schedule = ScheduleFactory(course_offering=offering, session_type='LECTURE')
        occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=offering, session_type='LECTURE')

        client.force_authenticate(user=doctor_user1)
        loc_data = {
            'latitude': 30.0444,
            'longitude': 31.2357,
            'location_accuracy_meters': 10.0,
            'location_captured_at': timezone.now().isoformat(),
        }
        res = client.post(f'/api/v1/attendance/occurrences/{occurrence.id}/open/', loc_data, format='json')
        assert res.status_code == 400
        assert res.data['code'] in ('COURSE_NOT_OWNED', 'COURSE_NOT_IN_SCOPE')


@pytest.mark.django_db
class TestTAWorkflow:
    def test_ta_today_work(self, client):
        org = OrganizationFactory()
        ta_user = TAUserFactory(organization=org)
        ta = TeachingAssistantFactory(user=ta_user)

        course = CourseFactory(organization=org)
        offering = CourseOfferingFactory(course=course)
        group = GroupFactory(course_offering=offering, teaching_assistant=ta)

        today_weekday = date.today().weekday()
        ScheduleFactory(course_offering=offering, group=group, day_of_week=today_weekday, session_type='LAB')

        client.force_authenticate(user=ta_user)
        res = client.get('/api/v1/attendance/today/')
        assert res.status_code == 200
        assert len(res.data) == 1
        assert res.data[0]['group_name'] == group.name
        assert res.data[0]['session_type'] == 'LAB'

    def test_ta_can_open_assigned_group_lab(self, client):
        org = OrganizationFactory()
        ta_user = TAUserFactory(organization=org)
        ta = TeachingAssistantFactory(user=ta_user)

        course = CourseFactory(organization=org)
        offering = CourseOfferingFactory(course=course)
        group = GroupFactory(course_offering=offering, teaching_assistant=ta)

        schedule = ScheduleFactory(course_offering=offering, group=group, session_type='LAB')
        occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=offering, group=group, session_type='LAB')

        client.force_authenticate(user=ta_user)
        loc_data = {
            'latitude': 30.0444,
            'longitude': 31.2357,
            'location_accuracy_meters': 10.0,
            'location_captured_at': timezone.now().isoformat(),
        }
        res = client.post(f'/api/v1/attendance/occurrences/{occurrence.id}/open/', loc_data, format='json')
        assert res.status_code == 201

    def test_ta_cannot_open_lecture(self, client):
        org = OrganizationFactory()
        ta_user = TAUserFactory(organization=org)
        ta = TeachingAssistantFactory(user=ta_user)

        course = CourseFactory(organization=org)
        offering = CourseOfferingFactory(course=course)
        schedule = ScheduleFactory(course_offering=offering, session_type='LECTURE')
        occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=offering, session_type='LECTURE')

        client.force_authenticate(user=ta_user)
        loc_data = {
            'latitude': 30.0444,
            'longitude': 31.2357,
            'location_accuracy_meters': 10.0,
            'location_captured_at': timezone.now().isoformat(),
        }
        res = client.post(f'/api/v1/attendance/occurrences/{occurrence.id}/open/', loc_data, format='json')
        assert res.status_code == 400
        assert res.data['code'] in ('LECTURE_NOT_ALLOWED', 'INVALID_SESSION_TYPE')


@pytest.mark.django_db
class TestSessionCloseNoReopen:
    def test_close_session_is_permanent(self, client):
        org = OrganizationFactory()
        doctor_user = DoctorUserFactory(organization=org)
        doctor = DoctorFactory(user=doctor_user)

        course = CourseFactory(organization=org)
        offering = CourseOfferingFactory(course=course, doctor=doctor)
        schedule = ScheduleFactory(course_offering=offering, session_type='LECTURE')
        occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=offering, session_type='LECTURE')
        session = AttendanceSessionFactory(occurrence=occurrence, organization=org, opened_by=doctor_user, status=SessionStatus.ACTIVE)

        client.force_authenticate(user=doctor_user)
        res = client.post(f'/api/v1/attendance/sessions/{session.id}/close/')
        assert res.status_code == 200

        session.refresh_from_db()
        assert session.status == SessionStatus.CLOSED

        res2 = client.post(f'/api/v1/attendance/sessions/{session.id}/close/')
        assert res2.status_code == 400
        assert res2.data['code'] == 'SESSION_ALREADY_CLOSED'
