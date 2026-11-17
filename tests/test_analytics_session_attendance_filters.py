"""
Tests for Analytics Session Attendance filtering and sorting:
- Status filters (PRESENT, LATE, ABSENT, EXCUSED, CHEATING, ALL)
- Quick search filter (student_id, student_name)
- Group / Section filter
- GPS / distance filters (WITHIN_ANCHOR, OUTSIDE_ANCHOR, NO_GPS)
- Multi-column sorting (name, id, status, distance, time)
- Web view session drill-down page rendering with metrics and all_rows_json
- Filtered Excel export verification
"""

from datetime import date
from io import BytesIO
import pytest
from openpyxl import load_workbook
from rest_framework.test import APIClient
from django.test import Client

from apps.attendance.models import AttendanceRecord, SessionStatus
from apps.analytics.services import AnalyticsService
from tests.factories import (
    OrganizationFactory, DoctorUserFactory, DoctorFactory, TAUserFactory,
    TeachingAssistantFactory, StudentFactory, CourseFactory, CourseOfferingFactory,
    GroupFactory, StudentEnrollmentFactory, ScheduleFactory, SessionOccurrenceFactory,
    AttendanceSessionFactory,
)


@pytest.fixture
def session_scope():
    org = OrganizationFactory()
    doctor_user = DoctorUserFactory(organization=org)
    doctor = DoctorFactory(user=doctor_user, organization=org)
    ta_user = TAUserFactory(organization=org)
    ta = TeachingAssistantFactory(user=ta_user, organization=org)
    course = CourseFactory(organization=org, code='CS301', name='Operating Systems')
    offering = CourseOfferingFactory(course=course, doctor=doctor)

    group_a = GroupFactory(course_offering=offering, name='Section 1')
    group_b = GroupFactory(course_offering=offering, name='Section 2')

    # Student 1: Present, group A, within anchor (15m)
    s1 = StudentFactory(user__organization=org, user__first_name='Alice', user__last_name='Smith', student_id='2024001')
    StudentEnrollmentFactory(student=s1, course_offering=offering, group=group_a)

    # Student 2: Late, group A, outside anchor (80m)
    s2 = StudentFactory(user__organization=org, user__first_name='Bob', user__last_name='Johnson', student_id='2024002')
    StudentEnrollmentFactory(student=s2, course_offering=offering, group=group_a)

    # Student 3: Absent, group B, no GPS
    s3 = StudentFactory(user__organization=org, user__first_name='Charlie', user__last_name='Davis', student_id='2024003')
    StudentEnrollmentFactory(student=s3, course_offering=offering, group=group_b)

    # Student 4: Excused, group B, no GPS
    s4 = StudentFactory(user__organization=org, user__first_name='Diana', user__last_name='Evans', student_id='2024004')
    StudentEnrollmentFactory(student=s4, course_offering=offering, group=group_b)

    schedule = ScheduleFactory(course_offering=offering, group=None, session_type='LECTURE')
    occurrence = SessionOccurrenceFactory(
        schedule=schedule,
        course_offering=offering,
        group=None,
        session_type='LECTURE',
        scheduled_date=date.today(),
    )
    session = AttendanceSessionFactory(
        occurrence=occurrence,
        organization=org,
        opened_by=doctor_user,
        status=SessionStatus.CLOSED,
    )

    AttendanceRecord.objects.create(
        session=session,
        student=s1,
        status='PRESENT',
        distance_from_location_meters=15.0,
        location_accuracy_meters=3.0,
    )
    AttendanceRecord.objects.create(
        session=session,
        student=s2,
        status='LATE',
        distance_from_location_meters=80.0,
        location_accuracy_meters=5.0,
    )
    AttendanceRecord.objects.create(
        session=session,
        student=s4,
        status='EXCUSED',
    )
    # s3 has no record -> ABSENT

    return {
        'org': org,
        'doctor_user': doctor_user,
        'session': session,
        'students': [s1, s2, s3, s4],
        's1': s1,
        's2': s2,
        's3': s3,
        's4': s4,
        'group_a': group_a,
        'group_b': group_b,
    }


@pytest.mark.django_db
class TestSessionAttendanceFilters:

    def test_status_filters(self, session_scope):
        svc = AnalyticsService()
        doc = session_scope['doctor_user']
        sess_id = session_scope['session'].id

        # ALL
        _, rows_all = svc.session_attendance_rows(doc, sess_id, {'attendance_status': 'ALL'})
        assert len(rows_all) == 4

        # PRESENT
        _, rows_present = svc.session_attendance_rows(doc, sess_id, {'attendance_status': 'PRESENT'})
        assert len(rows_present) == 1
        assert rows_present[0]['student_id'] == '2024001'

        # LATE
        _, rows_late = svc.session_attendance_rows(doc, sess_id, {'attendance_status': 'LATE'})
        assert len(rows_late) == 1
        assert rows_late[0]['student_id'] == '2024002'

        # ABSENT
        _, rows_absent = svc.session_attendance_rows(doc, sess_id, {'attendance_status': 'ABSENT'})
        assert len(rows_absent) == 1
        assert rows_absent[0]['student_id'] == '2024003'

        # EXCUSED
        _, rows_excused = svc.session_attendance_rows(doc, sess_id, {'attendance_status': 'EXCUSED'})
        assert len(rows_excused) == 1
        assert rows_excused[0]['student_id'] == '2024004'

    def test_search_filter(self, session_scope):
        svc = AnalyticsService()
        doc = session_scope['doctor_user']
        sess_id = session_scope['session'].id

        # Search by ID
        _, rows = svc.session_attendance_rows(doc, sess_id, {'search': '2024001'})
        assert len(rows) == 1
        assert rows[0]['student_name'] == 'Alice Smith'

        # Search by Name
        _, rows = svc.session_attendance_rows(doc, sess_id, {'search': 'charlie'})
        assert len(rows) == 1
        assert rows[0]['student_id'] == '2024003'

    def test_group_filter(self, session_scope):
        svc = AnalyticsService()
        doc = session_scope['doctor_user']
        sess_id = session_scope['session'].id

        # Section 1
        _, rows = svc.session_attendance_rows(doc, sess_id, {'group': 'Section 1'})
        assert len(rows) == 2
        assert {r['student_id'] for r in rows} == {'2024001', '2024002'}

        # Section 2
        _, rows = svc.session_attendance_rows(doc, sess_id, {'group': 'Section 2'})
        assert len(rows) == 2
        assert {r['student_id'] for r in rows} == {'2024003', '2024004'}

    def test_distance_filter(self, session_scope):
        svc = AnalyticsService()
        doc = session_scope['doctor_user']
        sess_id = session_scope['session'].id

        # WITHIN_ANCHOR (<= 50m)
        _, rows = svc.session_attendance_rows(doc, sess_id, {'distance_filter': 'WITHIN_ANCHOR'})
        assert len(rows) == 1
        assert rows[0]['student_id'] == '2024001'

        # OUTSIDE_ANCHOR (> 50m)
        _, rows = svc.session_attendance_rows(doc, sess_id, {'distance_filter': 'OUTSIDE_ANCHOR'})
        assert len(rows) == 1
        assert rows[0]['student_id'] == '2024002'

        # NO_GPS
        _, rows = svc.session_attendance_rows(doc, sess_id, {'distance_filter': 'NO_GPS'})
        assert len(rows) == 2
        assert {r['student_id'] for r in rows} == {'2024003', '2024004'}

    def test_sorting(self, session_scope):
        svc = AnalyticsService()
        doc = session_scope['doctor_user']
        sess_id = session_scope['session'].id

        # Sort by student_name asc
        _, rows = svc.session_attendance_rows(doc, sess_id, {'sort': 'student_name', 'ordering': 'asc'})
        names = [r['student_name'] for r in rows]
        assert names == sorted(names)

        # Sort by student_name desc
        _, rows = svc.session_attendance_rows(doc, sess_id, {'sort': 'student_name', 'ordering': 'desc'})
        names = [r['student_name'] for r in rows]
        assert names == sorted(names, reverse=True)

        # Sort by student_id desc
        _, rows = svc.session_attendance_rows(doc, sess_id, {'sort': 'student_id', 'ordering': 'desc'})
        assert [r['student_id'] for r in rows] == ['2024004', '2024003', '2024002', '2024001']

        # Sort by status asc: PRESENT (1), LATE (2), EXCUSED (3), CHEATING (4), ABSENT (5)
        _, rows = svc.session_attendance_rows(doc, sess_id, {'sort': 'status', 'ordering': 'asc'})
        statuses = [r['status'] for r in rows]
        assert statuses == ['PRESENT', 'LATE', 'EXCUSED', 'ABSENT']

    def test_web_page_renders_with_metrics_and_all_rows_json(self, session_scope):
        client = Client()
        client.force_login(session_scope['doctor_user'])
        sess_id = session_scope['session'].id

        response = client.get(f'/analytics/sessions/{sess_id}/')
        assert response.status_code == 200

        content = response.content.decode('utf-8')
        assert 'CS301' in content
        assert 'Alice Smith' in content
        assert 'Bob Johnson' in content
        assert 'Total Enrolled' in content
        assert 'all-rows-data' in content
        assert 'filter-search' in content
        assert 'filter-status' in content
        assert 'filter-sort' in content

    def test_excel_export_respects_active_filters(self, session_scope):
        client = APIClient()
        client.force_authenticate(user=session_scope['doctor_user'])
        sess_id = session_scope['session'].id

        # Export with PRESENT filter
        response = client.get('/api/v1/analytics/export/session/', {
            'session_id': sess_id,
            'attendance_status': 'PRESENT',
        })
        assert response.status_code == 200
        workbook = load_workbook(BytesIO(response.content))
        sheet = workbook['Session Attendance']
        # Row 1 is header, row 2 is the 1 matching student
        assert sheet.max_row == 2
        assert sheet['A2'].value == '2024001'
        assert sheet['D2'].value == 'PRESENT'
