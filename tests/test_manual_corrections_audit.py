"""
Manual Corrections & Audit Trail Tests.
Covers manual override authorization, status validation (LATE, EXCUSED, CHEATING),
scoped permissions, and complete audit logging.
"""

import pytest
from rest_framework.test import APIClient

from apps.attendance.models import AttendanceRecord, SessionStatus
from apps.audit.models import AuditLog, AuditAction

from tests.factories import (
    OrganizationFactory, AdminUserFactory, DoctorUserFactory, TAUserFactory,
    DoctorFactory, TeachingAssistantFactory, StudentFactory, CourseFactory,
    CourseOfferingFactory, GroupFactory, StudentEnrollmentFactory, ScheduleFactory,
    SessionOccurrenceFactory, AttendanceSessionFactory,
)


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestManualCorrectionsAndAudit:
    def test_doctor_manual_correction_excused_with_reason(self, client):
        org = OrganizationFactory()
        doctor_user = DoctorUserFactory(organization=org)
        doctor = DoctorFactory(user=doctor_user)

        course = CourseFactory(organization=org)
        offering = CourseOfferingFactory(course=course, doctor=doctor)
        student = StudentFactory(user__organization=org)
        StudentEnrollmentFactory(student=student, course_offering=offering)

        schedule = ScheduleFactory(course_offering=offering, session_type='LECTURE')
        occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=offering, session_type='LECTURE')
        session = AttendanceSessionFactory(occurrence=occurrence, organization=org, opened_by=doctor_user, status=SessionStatus.ACTIVE)

        client.force_authenticate(user=doctor_user)

        res = client.post(f'/api/v1/attendance/sessions/{session.id}/override/', {
            'student_id': student.id,
            'status': 'EXCUSED',
            'reason': 'Medical excuse submitted',
        })
        assert res.status_code in (200, 201)

        record = AttendanceRecord.objects.get(session=session, student=student)
        assert record.status == 'EXCUSED'

        # Verify Audit log
        log = AuditLog.objects.filter(target_type='AttendanceRecord', target_id=str(record.id)).last()
        assert log is not None
        assert log.actor == doctor_user
        assert log.metadata['reason'] == 'Medical excuse submitted'
        assert log.metadata['new_status'] == 'EXCUSED'

    def test_ta_manual_correction_cheating(self, client):
        org = OrganizationFactory()
        ta_user = TAUserFactory(organization=org)
        ta = TeachingAssistantFactory(user=ta_user)

        course = CourseFactory(organization=org)
        offering = CourseOfferingFactory(course=course)
        group = GroupFactory(course_offering=offering, teaching_assistant=ta)
        student = StudentFactory(user__organization=org)
        StudentEnrollmentFactory(student=student, course_offering=offering, group=group)

        schedule = ScheduleFactory(course_offering=offering, group=group, session_type='LAB')
        occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=offering, group=group, session_type='LAB')
        session = AttendanceSessionFactory(occurrence=occurrence, organization=org, opened_by=ta_user, status=SessionStatus.ACTIVE)

        client.force_authenticate(user=ta_user)

        res = client.post(f'/api/v1/attendance/sessions/{session.id}/override/', {
            'student_id': student.id,
            'status': 'CHEATING',
            'reason': 'Proxy check-in detected',
        })
        assert res.status_code in (200, 201)

        record = AttendanceRecord.objects.get(session=session, student=student)
        assert record.status == 'CHEATING'

    def test_ta_cannot_override_unassigned_group_session(self, client):
        org = OrganizationFactory()
        ta_user1 = TAUserFactory(organization=org)
        ta1 = TeachingAssistantFactory(user=ta_user1)
        ta2 = TeachingAssistantFactory(user__organization=org)

        course = CourseFactory(organization=org)
        offering = CourseOfferingFactory(course=course)
        group_b = GroupFactory(course_offering=offering, teaching_assistant=ta2)
        student = StudentFactory(user__organization=org)

        schedule = ScheduleFactory(course_offering=offering, group=group_b, session_type='LAB')
        occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=offering, group=group_b, session_type='LAB')
        session = AttendanceSessionFactory(occurrence=occurrence, organization=org, status=SessionStatus.ACTIVE)

        client.force_authenticate(user=ta_user1)

        res = client.post(f'/api/v1/attendance/sessions/{session.id}/override/', {
            'student_id': student.id,
            'status': 'EXCUSED',
            'reason': 'Unauthorized override',
        })
        assert res.status_code == 403
