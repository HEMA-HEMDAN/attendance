"""
Organization Isolation & Multi-Tenancy Tests.
Verifies complete multi-tenant isolation across Org A and Org B for List and Detail routes.
"""

import pytest
from rest_framework.test import APIClient
from apps.attendance.models import SessionStatus

from tests.factories import (
    OrganizationFactory, AdminUserFactory, DoctorFactory, TeachingAssistantFactory,
    StudentFactory, CourseFactory, CourseOfferingFactory, GroupFactory,
    StudentEnrollmentFactory, ScheduleFactory, SessionOccurrenceFactory,
    AttendanceSessionFactory,
)


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestOrganizationIsolationDetailed:
    def test_admin_cannot_access_other_org_detail_by_id(self, client):
        org_a = OrganizationFactory(name='Org A', slug='org-a')
        org_b = OrganizationFactory(name='Org B', slug='org-b')

        admin_a = AdminUserFactory(organization=org_a)
        student_b = StudentFactory(user__organization=org_b)

        client.force_authenticate(user=admin_a)

        # Detail route by ID
        res = client.get(f'/api/v1/students/{student_b.id}/')
        assert res.status_code == 404

    def test_doctor_cannot_access_other_org_courses(self, client):
        org_a = OrganizationFactory()
        org_b = OrganizationFactory()

        doc_a = DoctorFactory(user__organization=org_a)
        course_b = CourseFactory(organization=org_b)
        offering_b = CourseOfferingFactory(course=course_b)

        client.force_authenticate(user=doc_a.user)

        res = client.get('/api/v1/courses/offerings/')
        assert res.status_code == 200
        ids = [item['id'] for item in res.data['results']]
        assert offering_b.id not in ids

    def test_ta_cannot_access_other_org_groups(self, client):
        org_a = OrganizationFactory()
        org_b = OrganizationFactory()

        ta_a = TeachingAssistantFactory(user__organization=org_a)
        course_b = CourseFactory(organization=org_b)
        offering_b = CourseOfferingFactory(course=course_b)
        group_b = GroupFactory(course_offering=offering_b)

        client.force_authenticate(user=ta_a.user)

        res = client.get(f'/api/v1/groups/{group_b.id}/')
        assert res.status_code == 404

    def test_student_cannot_checkin_to_other_org_session(self, client):
        org_a = OrganizationFactory()
        org_b = OrganizationFactory()

        student_a = StudentFactory(user__organization=org_a)

        course_b = CourseFactory(organization=org_b)
        offering_b = CourseOfferingFactory(course=course_b)
        group_b = GroupFactory(course_offering=offering_b)
        schedule_b = ScheduleFactory(course_offering=offering_b, group=group_b)
        occ_b = SessionOccurrenceFactory(schedule=schedule_b, course_offering=offering_b, group=group_b)
        session_b = AttendanceSessionFactory(occurrence=occ_b, organization=org_b, status=SessionStatus.ACTIVE)

        client.force_authenticate(user=student_a.user)

        res = client.post(f'/api/v1/attendance/sessions/{session_b.id}/checkin/', {
            'device_id': 1,
            'challenge_token': 'dummy',
            'signature': 'dummy',
        })
        assert res.status_code == 400
        assert res.data['code'] in ('ORG_MISMATCH', 'ENROLLMENT_MISMATCH', 'SESSION_NOT_FOUND')
