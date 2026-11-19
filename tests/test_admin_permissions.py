import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.accounts.admin_permissions import configure_organization_admin
from apps.accounts.models import Role
from apps.courses.models import AcademicYear
from tests.factories import (
    AdminUserFactory,
    CourseFactory,
    DoctorUserFactory,
    OrganizationFactory,
    StudentUserFactory,
    TAUserFactory,
)


User = get_user_model()


@pytest.fixture
def admin_client():
    return Client()


@pytest.mark.django_db
class TestDjangoAdminPermissions:
    def test_superadmin_can_access_admin_and_platform_resources(self, admin_client):
        superadmin = User.objects.create_superuser(
            email='root@example.com', password='testpass123',
        )
        assert admin_client.login(email=superadmin.email, password='testpass123')

        assert admin_client.get('/admin/').status_code == 200
        assert admin_client.get('/admin/organizations/organization/').status_code == 200

    def test_organization_admin_can_access_scoped_admin(self, admin_client):
        organization = OrganizationFactory(slug='admin-org')
        admin = AdminUserFactory(organization=organization)
        configure_organization_admin(admin)
        admin.refresh_from_db()

        assert admin.is_staff is True
        assert admin.is_superuser is False
        assert admin_client.login(email=admin.email, password='testpass123')
        assert admin_client.get('/admin/').status_code == 200

    def test_organization_admin_sees_only_own_organization_records(self, admin_client):
        own = OrganizationFactory(slug='own-org')
        other = OrganizationFactory(slug='other-org')
        own_course = CourseFactory(organization=own, code='OWN-101')
        other_course = CourseFactory(organization=other, code='OTHER-101')
        admin = AdminUserFactory(organization=own)
        configure_organization_admin(admin)

        assert admin_client.login(email=admin.email, password='testpass123')
        response = admin_client.get('/admin/courses/course/')
        assert response.status_code == 200
        assert own_course.name.encode() in response.content
        assert other_course.name.encode() not in response.content

        assert admin_client.get(f'/admin/courses/course/{other_course.pk}/change/').status_code in (302, 404)

    def test_organization_admin_academic_year_uses_own_organization(self, admin_client):
        organization = OrganizationFactory(slug='academic-year-admin-org')
        admin = AdminUserFactory(organization=organization)
        configure_organization_admin(admin)
        assert admin_client.login(email=admin.email, password='testpass123')

        response = admin_client.get('/admin/courses/academicyear/add/')
        assert response.status_code == 200
        assert 'organization' not in response.context['adminform'].form.fields

        response = admin_client.post('/admin/courses/academicyear/add/', {
            'name': '2026/2027',
            'start_date': '2026-09-01',
            'end_date': '2027-06-30',
            'is_active': 'on',
        })
        assert response.status_code == 302
        academic_year = AcademicYear.objects.get(name='2026/2027')
        assert academic_year.organization == organization

    def test_organization_admin_cannot_access_platform_resources(self, admin_client):
        organization = OrganizationFactory()
        admin = AdminUserFactory(organization=organization)
        configure_organization_admin(admin)
        assert admin_client.login(email=admin.email, password='testpass123')

        assert admin_client.get('/admin/organizations/organization/').status_code == 403
        assert admin_client.get('/admin/auth/group/').status_code == 403
        assert admin_client.get('/admin/accounts/user/').status_code in (403, 404)
        assert not admin.has_perm('auth.add_group')
        assert not admin.has_perm('auth.change_group')

    def test_organization_admin_cannot_escalate_privileges(self, admin_client):
        organization = OrganizationFactory()
        admin = AdminUserFactory(organization=organization)
        configure_organization_admin(admin)
        assert admin_client.login(email=admin.email, password='testpass123')

        assert admin_client.get(f'/admin/accounts/user/{admin.pk}/change/').status_code in (302, 403, 404)
        assert admin_client.get('/admin/auth/group/add/').status_code in (302, 403, 404)

    @pytest.mark.parametrize('factory', [DoctorUserFactory, TAUserFactory, StudentUserFactory])
    def test_normal_mobile_roles_cannot_access_admin(self, admin_client, factory):
        user = factory()
        assert user.is_staff is False
        assert admin_client.get('/admin/').status_code == 302