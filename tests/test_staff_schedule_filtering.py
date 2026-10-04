import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from apps.staff.admin import DoctorAdmin, TeachingAssistantAdmin, DoctorScheduleInline, TAScheduleInline
from apps.staff.models import Doctor, TeachingAssistant
from apps.courses.models import CourseOffering, Schedule, SessionType
from apps.courses.forms import ScheduleAdminForm, GroupSelectWidget
from apps.groups.models import Group
from tests.factories import (
    OrganizationFactory, AdminUserFactory, DoctorUserFactory, TAUserFactory, DoctorFactory, TeachingAssistantFactory,
    CourseOfferingFactory, GroupFactory
)

@pytest.mark.django_db
class TestStaffScheduleFiltering:
    def test_doctor_schedule_inline_filters_to_doctor_courses_and_groups(self):
        org = OrganizationFactory()
        admin_user = AdminUserFactory(organization=org)
        doc1 = DoctorFactory(user=DoctorUserFactory(organization=org))
        doc2 = DoctorFactory(user=DoctorUserFactory(organization=org))

        co1 = CourseOfferingFactory(doctor=doc1, course__organization=org)
        co2 = CourseOfferingFactory(doctor=doc2, course__organization=org)

        grp1 = GroupFactory(course_offering=co1)
        grp2 = GroupFactory(course_offering=co2)

        site = AdminSite()
        inline = DoctorScheduleInline(Doctor, site)

        rf = RequestFactory()
        request = rf.get(f'/admin/staff/doctor/{doc1.id}/change/')
        request.user = admin_user

        # Mock formset call storing _editing_doctor
        inline.get_formset(request, obj=doc1)

        co_field = inline.formfield_for_foreignkey(Schedule._meta.get_field('course_offering'), request)
        grp_field = inline.formfield_for_foreignkey(Schedule._meta.get_field('group'), request)

        assert co1 in co_field.queryset
        assert co2 not in co_field.queryset

        assert grp1 in grp_field.queryset
        assert grp2 not in grp_field.queryset

    def test_ta_schedule_inline_filters_to_ta_groups_and_courses(self):
        org = OrganizationFactory()
        admin_user = AdminUserFactory(organization=org)
        ta1 = TeachingAssistantFactory(user=TAUserFactory(organization=org))
        ta2 = TeachingAssistantFactory(user=TAUserFactory(organization=org))

        co1 = CourseOfferingFactory(course__organization=org)
        co2 = CourseOfferingFactory(course__organization=org)

        grp1 = GroupFactory(course_offering=co1, teaching_assistant=ta1)
        grp2 = GroupFactory(course_offering=co2, teaching_assistant=ta2)

        site = AdminSite()
        inline = TAScheduleInline(TeachingAssistant, site)

        rf = RequestFactory()
        request = rf.get(f'/admin/staff/teachingassistant/{ta1.id}/change/')
        request.user = admin_user

        inline.get_formset(request, obj=ta1)

        grp_field = inline.formfield_for_foreignkey(Schedule._meta.get_field('group'), request)
        co_field = inline.formfield_for_foreignkey(Schedule._meta.get_field('course_offering'), request)

        assert grp1 in grp_field.queryset
        assert grp2 not in grp_field.queryset

        assert co1 in co_field.queryset
        assert co2 not in co_field.queryset

    def test_group_select_widget_attaches_data_course_offering_attribute(self):
        org = OrganizationFactory()
        co = CourseOfferingFactory(course__organization=org)
        group = GroupFactory(course_offering=co)

        from django import forms
        field = forms.ModelChoiceField(queryset=Group.objects.all(), widget=GroupSelectWidget())
        html = field.widget.render('group', None)
        assert f'data-course-offering="{co.id}"' in html

    def test_schedule_admin_form_rejects_mismatched_group_and_course_offering(self):
        org = OrganizationFactory()
        co1 = CourseOfferingFactory(course__organization=org)
        co2 = CourseOfferingFactory(course__organization=org)
        group1 = GroupFactory(course_offering=co1)

        form_data = {
            'course_offering': co2.id,
            'group': group1.id,
            'session_type': SessionType.LAB,
            'day_of_week': 1,
            'start_time': '10:00:00',
            'end_time': '12:00:00',
            'is_active': True,
        }

        form = ScheduleAdminForm(data=form_data)
        assert not form.is_valid()
        assert 'group' in form.errors
        assert f"Group '{group1.name}' does not belong to course offering '{co2}'" in form.errors['group'][0]
