import pytest
from django.contrib.admin.sites import AdminSite
from django.utils import timezone

from apps.staff.admin import DoctorAdmin, TeachingAssistantAdmin, DoctorScheduleInline, TAScheduleInline
from apps.staff.models import Doctor, TeachingAssistant
from apps.courses.models import CourseOffering, Schedule, SessionType
from apps.groups.models import Group
from tests.factories import (
    OrganizationFactory, DoctorUserFactory, TAUserFactory, DoctorFactory, TeachingAssistantFactory,
    CourseOfferingFactory, GroupFactory, ScheduleFactory
)

@pytest.mark.django_db
class TestAllInOneStaffSchedules:
    def test_doctor_schedule_inline_auto_populates_doctor(self):
        org = OrganizationFactory()
        doctor = DoctorFactory(user=DoctorUserFactory(organization=org))
        co = CourseOfferingFactory(doctor=doctor, course__organization=org)
        
        # Create schedule with doctor set directly
        sch = Schedule.objects.create(
            course_offering=co,
            session_type=SessionType.LECTURE,
            day_of_week=0,
            start_time="09:00:00",
            end_time="11:00:00",
        )
        
        # doctor should be auto-derived from course offering doctor
        assert sch.doctor == doctor
        assert sch in doctor.schedules.all()

    def test_ta_schedule_inline_auto_populates_ta(self):
        org = OrganizationFactory()
        ta = TeachingAssistantFactory(user=TAUserFactory(organization=org))
        co = CourseOfferingFactory(course__organization=org)
        group = GroupFactory(course_offering=co, teaching_assistant=ta)

        sch = Schedule.objects.create(
            course_offering=co,
            group=group,
            session_type=SessionType.LAB,
            day_of_week=2,
            start_time="12:00:00",
            end_time="14:00:00",
        )

        # teaching_assistant should be auto-derived from group TA
        assert sch.teaching_assistant == ta
        assert sch in ta.schedules.all()

    def test_doctor_admin_has_doctor_schedule_inline(self):
        site = AdminSite()
        doctor_admin = DoctorAdmin(Doctor, site)
        inline_classes = [inline.__name__ for inline in doctor_admin.inlines]
        assert 'DoctorScheduleInline' in inline_classes

    def test_ta_admin_has_ta_schedule_inline(self):
        site = AdminSite()
        ta_admin = TeachingAssistantAdmin(TeachingAssistant, site)
        inline_classes = [inline.__name__ for inline in ta_admin.inlines]
        assert 'TAScheduleInline' in inline_classes

    def test_inline_explicit_assignment_updates_course_offering_and_group(self):
        org = OrganizationFactory()
        doctor = DoctorFactory(user=DoctorUserFactory(organization=org))
        ta = TeachingAssistantFactory(user=TAUserFactory(organization=org))
        
        co = CourseOfferingFactory(doctor=None, course__organization=org)
        group = GroupFactory(course_offering=co, teaching_assistant=None)

        # Create schedule directly assigning doctor and TA
        sch = Schedule.objects.create(
            course_offering=co,
            group=group,
            doctor=doctor,
            teaching_assistant=ta,
            session_type=SessionType.LAB,
            day_of_week=1,
            start_time="10:00:00",
            end_time="12:00:00",
        )

        co.refresh_from_db()
        group.refresh_from_db()

        assert co.doctor == doctor
        assert group.teaching_assistant == ta
