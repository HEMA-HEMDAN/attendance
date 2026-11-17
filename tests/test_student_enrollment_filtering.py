import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from django import forms

from apps.students.admin import StudentAdmin, StudentEnrollmentAdmin, StudentEnrollmentInline
from apps.students.models import Student, StudentEnrollment
from apps.courses.models import CourseOffering
from apps.courses.forms import GroupSelectWidget
from apps.groups.models import Group
from apps.students.admin import StudentEnrollmentAdminForm
from tests.factories import (
    OrganizationFactory, AdminUserFactory, StudentFactory,
    CourseOfferingFactory, GroupFactory
)


@pytest.mark.django_db
class TestStudentEnrollmentFiltering:
    def test_group_select_widget_renders_data_course_offering_attribute(self):
        org = OrganizationFactory()
        co = CourseOfferingFactory(course__organization=org)
        group = GroupFactory(course_offering=co)

        field = forms.ModelChoiceField(queryset=Group.objects.all(), widget=GroupSelectWidget())
        html = field.widget.render('group', None)
        assert f'data-course-offering="{co.id}"' in html

    def test_student_enrollment_form_validates_group_belongs_to_course_offering(self):
        org = OrganizationFactory()
        student = StudentFactory(organization=org)
        co1 = CourseOfferingFactory(course__organization=org)
        co2 = CourseOfferingFactory(course__organization=org)
        group1 = GroupFactory(course_offering=co1)

        form_data = {
            'student': student.id,
            'course_offering': co2.id,
            'group': group1.id,
        }

        form = StudentEnrollmentAdminForm(data=form_data)
        assert not form.is_valid()
        assert 'group' in form.errors
        assert f"Group '{group1.name}' does not belong to course offering '{co2}'." in form.errors['group'][0]

    def test_student_enrollment_form_valid_when_group_matches_course_offering(self):
        org = OrganizationFactory()
        student = StudentFactory(organization=org)
        co1 = CourseOfferingFactory(course__organization=org)
        group1 = GroupFactory(course_offering=co1)

        form_data = {
            'student': student.id,
            'course_offering': co1.id,
            'group': group1.id,
        }

        form = StudentEnrollmentAdminForm(data=form_data)
        assert form.is_valid()

    def test_student_enrollment_inline_media_includes_schedule_group_filter_js(self):
        site = AdminSite()
        inline = StudentEnrollmentInline(Student, site)
        media_js = list(inline.media._js)
        assert 'admin/js/schedule_group_filter.js' in media_js

    def test_student_enrollment_admin_media_includes_schedule_group_filter_js(self):
        site = AdminSite()
        admin_obj = StudentEnrollmentAdmin(StudentEnrollment, site)
        media_js = list(admin_obj.media._js)
        assert 'admin/js/schedule_group_filter.js' in media_js

    def test_get_groups_by_offering_endpoint_returns_matching_groups(self):
        from apps.courses.views import get_groups_by_offering

        org = OrganizationFactory()
        admin_user = AdminUserFactory(organization=org)

        co1 = CourseOfferingFactory(course__organization=org)
        co2 = CourseOfferingFactory(course__organization=org)
        group1 = GroupFactory(course_offering=co1, name="Section A")
        group2 = GroupFactory(course_offering=co2, name="Section B")

        rf = RequestFactory()
        request = rf.get(f'/admin/groups-by-offering/?offering_id={co1.id}')
        request.user = admin_user

        response = get_groups_by_offering(request)
        assert response.status_code == 200

        import json
        data = json.loads(response.content.decode('utf-8'))
        assert 'groups' in data
        group_ids = [g['id'] for g in data['groups']]
        assert group1.id in group_ids
        assert group2.id not in group_ids
