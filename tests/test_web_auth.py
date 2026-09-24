"""
Browser session authentication tests for the analytics dashboard.

JWT/API login at /api/v1/auth/login/ remains a separate contract and is regression-tested here.
"""

import pytest
from django.test import Client
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from tests.factories import (
    OrganizationFactory, AdminUserFactory, DoctorUserFactory, TAUserFactory,
    StudentUserFactory, DoctorFactory, TeachingAssistantFactory,
    CourseOfferingFactory, GroupFactory,
)


@pytest.fixture
def browser():
    return Client()


@pytest.mark.django_db
class TestWebLogin:
    def test_valid_credentials_create_django_session(self, browser):
        org = OrganizationFactory()
        doctor = DoctorUserFactory(organization=org)

        res = browser.post('/login/', {
            'email': doctor.email,
            'password': 'testpass123',
        })
        assert res.status_code == 302
        assert res.url == '/analytics/dashboard/'
        assert '_auth_user_id' in browser.session
        assert int(browser.session['_auth_user_id']) == doctor.id

    def test_invalid_credentials_are_rejected(self, browser):
        org = OrganizationFactory()
        doctor = DoctorUserFactory(organization=org)

        res = browser.post('/login/', {
            'email': doctor.email,
            'password': 'wrong-password',
        })
        assert res.status_code == 400
        assert '_auth_user_id' not in browser.session
        assert b'Invalid email or password' in res.content

    def test_successful_login_respects_next(self, browser):
        org = OrganizationFactory()
        admin = AdminUserFactory(organization=org)

        res = browser.post('/login/', {
            'email': admin.email,
            'password': 'testpass123',
            'next': '/analytics/dashboard/',
        })
        assert res.status_code == 302
        assert res.url == '/analytics/dashboard/'

    def test_student_cannot_use_analytics_web_login(self, browser):
        org = OrganizationFactory()
        student = StudentUserFactory(organization=org)

        res = browser.post('/login/', {
            'email': student.email,
            'password': 'testpass123',
        })
        assert res.status_code == 403
        assert '_auth_user_id' not in browser.session


@pytest.mark.django_db
class TestWebAnalyticsAccess:
    def test_unauthenticated_browser_redirects_to_login(self, browser):
        res = browser.get('/analytics/dashboard/')
        assert res.status_code == 302
        assert res.url.startswith('/login/')
        assert 'next=/analytics/dashboard/' in res.url

    def test_doctor_sees_doctor_scoped_dashboard(self, browser):
        org = OrganizationFactory()
        doc_user = DoctorUserFactory(organization=org)
        doc = DoctorFactory(user=doc_user, organization=org)
        offering = CourseOfferingFactory(doctor=doc)

        assert browser.login(username=doc_user.email, password='testpass123')
        res = browser.get('/analytics/dashboard/')
        assert res.status_code == 200
        assert b'Attendance & Performance Dashboard' in res.content or b'Attendance &amp; Performance Dashboard' in res.content
        assert offering.course.code.encode() in res.content
        assert b'DOCTOR' in res.content

    def test_ta_sees_ta_scoped_dashboard(self, browser):
        org = OrganizationFactory()
        ta_user = TAUserFactory(organization=org)
        ta = TeachingAssistantFactory(user=ta_user, organization=org)
        offering = CourseOfferingFactory(course__organization=org)
        group = GroupFactory(course_offering=offering, teaching_assistant=ta)

        assert browser.login(username=ta_user.email, password='testpass123')
        res = browser.get('/analytics/dashboard/')
        assert res.status_code == 200
        assert group.name.encode() in res.content
        assert b'TEACHING_ASSISTANT' in res.content

    def test_admin_sees_organization_dashboard(self, browser):
        org = OrganizationFactory(name='Org Alpha')
        admin = AdminUserFactory(organization=org)
        CourseOfferingFactory(course__organization=org)

        assert browser.login(username=admin.email, password='testpass123')
        res = browser.get('/analytics/dashboard/')
        assert res.status_code == 200
        assert b'ADMIN' in res.content

    def test_superadmin_sees_platform_dashboard(self, browser):
        superadmin = User.objects.create_user(
            email='websuper@example.com',
            password='testpass123',
            first_name='Super',
            last_name='Admin',
            role=Role.SUPERADMIN,
        )
        assert browser.login(username=superadmin.email, password='testpass123')
        res = browser.get('/analytics/dashboard/')
        assert res.status_code == 200
        assert b'SUPERADMIN' in res.content


@pytest.mark.django_db
class TestWebAnalyticsIsolation:
    def test_doctor_session_does_not_include_other_org_offerings(self, browser):
        org1 = OrganizationFactory()
        org2 = OrganizationFactory()
        doc_user1 = DoctorUserFactory(organization=org1)
        doc_user2 = DoctorUserFactory(organization=org2)
        doc1 = DoctorFactory(user=doc_user1, organization=org1)
        doc2 = DoctorFactory(user=doc_user2, organization=org2)
        offering1 = CourseOfferingFactory(doctor=doc1)
        offering2 = CourseOfferingFactory(doctor=doc2)

        assert browser.login(username=doc_user1.email, password='testpass123')
        res = browser.get('/analytics/dashboard/')
        assert res.status_code == 200
        assert offering1.course.code.encode() in res.content
        assert offering2.course.code.encode() not in res.content


@pytest.mark.django_db
class TestWebLogout:
    def test_logout_clears_session_and_dashboard_requires_login(self, browser):
        org = OrganizationFactory()
        doctor = DoctorUserFactory(organization=org)
        assert browser.login(username=doctor.email, password='testpass123')
        assert '_auth_user_id' in browser.session

        res = browser.get('/logout/')
        assert res.status_code == 302
        assert res.url == '/login/'
        assert '_auth_user_id' not in browser.session

        dash = browser.get('/analytics/dashboard/')
        assert dash.status_code == 302
        assert dash.url.startswith('/login/')


@pytest.mark.django_db
class TestJwtApiRegression:
    def test_jwt_login_contract_unchanged(self):
        api = APIClient()
        org = OrganizationFactory()
        doctor = DoctorUserFactory(organization=org)
        res = api.post('/api/v1/auth/login/', {
            'email': doctor.email,
            'password': 'testpass123',
        })
        assert res.status_code == 200
        assert 'access' in res.data
        assert 'refresh' in res.data
        assert res.data['user']['role'] == 'DOCTOR'

    def test_human_dashboard_does_not_require_jwt(self, browser):
        org = OrganizationFactory()
        doctor = DoctorUserFactory(organization=org)
        DoctorFactory(user=doctor, organization=org)
        assert browser.login(username=doctor.email, password='testpass123')
        res = browser.get('/analytics/dashboard/')
        assert res.status_code == 200

    def test_api_dashboard_still_requires_authentication(self):
        api = APIClient()
        res = api.get('/api/v1/analytics/dashboard/')
        assert res.status_code == 401
