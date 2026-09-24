"""Operational analytics, scoping, and Excel export tests."""

from datetime import date, timedelta
from io import BytesIO

import pytest
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.attendance.models import AttendanceRecord, SessionStatus
from apps.analytics.services import AnalyticsService
from tests.factories import (
    OrganizationFactory, DoctorUserFactory, DoctorFactory, TAUserFactory,
    TeachingAssistantFactory, StudentFactory, CourseFactory, CourseOfferingFactory,
    GroupFactory, StudentEnrollmentFactory, ScheduleFactory, SessionOccurrenceFactory,
    AttendanceSessionFactory,
)


@pytest.fixture
def client():
    return APIClient()


def make_scope():
    org = OrganizationFactory()
    doctor_user = DoctorUserFactory(organization=org)
    doctor = DoctorFactory(user=doctor_user, organization=org)
    ta_user = TAUserFactory(organization=org)
    ta = TeachingAssistantFactory(user=ta_user, organization=org)
    course = CourseFactory(organization=org)
    offering = CourseOfferingFactory(course=course, doctor=doctor)
    group = GroupFactory(course_offering=offering, teaching_assistant=ta)
    students = [StudentFactory(user__organization=org) for _ in range(2)]
    for student in students:
        StudentEnrollmentFactory(student=student, course_offering=offering, group=group)
    return org, doctor_user, doctor, ta_user, ta, offering, group, students


def make_closed_session(offering, group, doctor_user, session_date=None):
    schedule = ScheduleFactory(course_offering=offering, group=group, session_type='LAB')
    occurrence = SessionOccurrenceFactory(
        schedule=schedule,
        course_offering=offering,
        group=group,
        session_type='LAB',
        scheduled_date=session_date or date.today(),
    )
    return AttendanceSessionFactory(
        occurrence=occurrence,
        organization=offering.course.organization,
        opened_by=doctor_user,
        status=SessionStatus.CLOSED,
    )


@pytest.mark.django_db
class TestOperationalAnalytics:
    def test_student_summary_derives_absence_and_final_rate(self):
        org, doctor_user, doctor, ta_user, ta, offering, group, students = make_scope()
        first = make_closed_session(offering, group, doctor_user)
        second = make_closed_session(offering, group, doctor_user)
        AttendanceRecord.objects.create(session=first, student=students[0], status='PRESENT')
        AttendanceRecord.objects.create(session=second, student=students[0], status='EXCUSED')
        AttendanceRecord.objects.create(session=first, student=students[1], status='CHEATING')

        rows = AnalyticsService().student_summary_rows(doctor_user)
        by_id = {row['student_id']: row for row in rows}

        assert by_id[students[0].student_id]['eligible_sessions'] == 2
        assert by_id[students[0].student_id]['present'] == 1
        assert by_id[students[0].student_id]['excused'] == 1
        assert by_id[students[0].student_id]['absent'] == 0
        assert by_id[students[0].student_id]['attendance_rate'] == 100.0
        assert by_id[students[1].student_id]['cheating'] == 1
        assert by_id[students[1].student_id]['absent'] == 1

    def test_doctor_student_list_is_scoped_against_id_tampering(self, client):
        org, doctor_user, doctor, ta_user, ta, offering, group, students = make_scope()
        other_doctor_user = DoctorUserFactory(organization=org)
        other_doctor = DoctorFactory(user=other_doctor_user, organization=org)
        other_offering = CourseOfferingFactory(course__organization=org, doctor=other_doctor)
        other_group = GroupFactory(course_offering=other_offering)
        other_student = StudentFactory(user__organization=org)
        StudentEnrollmentFactory(student=other_student, course_offering=other_offering, group=other_group)

        client.force_authenticate(user=doctor_user)
        response = client.get('/api/v1/analytics/students/', {'course_offering_id': other_offering.id})

        assert response.status_code == 200
        assert response.data['count'] == 0
        assert other_student.student_id not in [row['student_id'] for row in response.data['results']]

    def test_ta_sees_only_assigned_group(self, client):
        org, doctor_user, doctor, ta_user, ta, offering, group, students = make_scope()
        other_group = GroupFactory(course_offering=offering)
        other_student = StudentFactory(user__organization=org)
        StudentEnrollmentFactory(student=other_student, course_offering=offering, group=other_group)

        client.force_authenticate(user=ta_user)
        response = client.get('/api/v1/analytics/students/', {'group_id': other_group.id})

        assert response.status_code == 200
        assert response.data['count'] == 0

    def test_session_details_include_absent_and_persisted_location(self, client):
        org, doctor_user, doctor, ta_user, ta, offering, group, students = make_scope()
        session = make_closed_session(offering, group, doctor_user)
        AttendanceRecord.objects.create(
            session=session,
            student=students[0],
            status='LATE',
            distance_from_location_meters=23.4,
            location_accuracy_meters=4.5,
        )

        client.force_authenticate(user=doctor_user)
        response = client.get(f'/api/v1/analytics/sessions/{session.id}/attendance/')

        assert response.status_code == 200
        rows = {row['student_id']: row for row in response.data['results']}
        assert rows[students[0].student_id]['status'] == 'LATE'
        assert rows[students[0].student_id]['distance_from_session_location'] == 23.4
        assert rows[students[0].student_id]['location_accuracy'] == 4.5
        assert rows[students[1].student_id]['status'] == 'ABSENT'
        assert rows[students[1].student_id]['distance_from_session_location'] is None

    def test_pagination_and_filtered_course_export(self, client):
        org, doctor_user, doctor, ta_user, ta, offering, group, students = make_scope()
        session = make_closed_session(offering, group, doctor_user)
        AttendanceRecord.objects.create(session=session, student=students[0], status='PRESENT')

        client.force_authenticate(user=doctor_user)
        response = client.get('/api/v1/analytics/students/', {'page_size': 1, 'page': 2})
        assert response.status_code == 200
        assert response.data['count'] == 2
        assert len(response.data['results']) == 1

        export = client.get('/api/v1/analytics/export/course/', {'group_id': group.id})
        assert export.status_code == 200
        workbook = load_workbook(BytesIO(export.content))
        sheet = workbook['Attendance Summary']
        assert sheet.max_row == 3
        assert sheet['A1'].value == 'Student ID'
        assert sheet['J1'].value == 'Attendance Rate'
        assert sheet['J2'].number_format == '0%'

    def test_student_history_export_is_scoped(self, client):
        org, doctor_user, doctor, ta_user, ta, offering, group, students = make_scope()
        session = make_closed_session(offering, group, doctor_user)
        AttendanceRecord.objects.create(session=session, student=students[0], status='PRESENT')

        client.force_authenticate(user=doctor_user)
        response = client.get('/api/v1/analytics/export/student/', {'student_id': students[0].id})

        assert response.status_code == 200
        workbook = load_workbook(BytesIO(response.content))
        assert workbook.sheetnames == ['Attendance Details']
        assert workbook.active.max_row == 2
