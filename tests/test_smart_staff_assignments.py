import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient
from rest_framework import status
from tests.factories import (
    OrganizationFactory, AdminUserFactory, DoctorFactory, TeachingAssistantFactory,
    CourseFactory, CourseOfferingFactory, GroupFactory, AcademicYearFactory, SemesterFactory, ScheduleFactory
)
from apps.courses.models import CourseOffering, Schedule
from apps.groups.models import Group


@pytest.mark.django_db
class TestSmartStaffAssignments:
    def setup_method(self):
        self.org = OrganizationFactory()
        self.admin_user = AdminUserFactory(organization=self.org)
        self.doctor = DoctorFactory(organization=self.org)
        self.ta = TeachingAssistantFactory(organization=self.org)

        self.ay = AcademicYearFactory(organization=self.org)
        self.sem = SemesterFactory(organization=self.org, academic_year=self.ay)

        self.course1 = CourseFactory(organization=self.org, code='CS201')
        self.course2 = CourseFactory(organization=self.org, code='CS202')

        self.offering1 = CourseOfferingFactory(course=self.course1, academic_year=self.ay, semester=self.sem, doctor=self.doctor)
        self.offering2 = CourseOfferingFactory(course=self.course2, academic_year=self.ay, semester=self.sem, doctor=self.doctor)

        self.group1 = GroupFactory(course_offering=self.offering1, teaching_assistant=self.ta, name='Lab 1')
        self.group2 = GroupFactory(course_offering=self.offering2, teaching_assistant=self.ta, name='Lab 2')

        self.client = APIClient()
        self.client.force_authenticate(user=self.admin_user)

    def test_doctor_can_teach_multiple_course_offerings(self):
        """Verify that a Doctor can lead multiple course offerings."""
        assert self.doctor.course_offerings.count() == 2
        assert set(self.doctor.course_offerings.values_list('id', flat=True)) == {
            self.offering1.id, self.offering2.id
        }

    def test_ta_can_be_assigned_multiple_groups(self):
        """Verify that a TA can be assigned to multiple lab groups across course offerings."""
        assert self.ta.assigned_groups.count() == 2
        assert set(self.ta.assigned_groups.values_list('id', flat=True)) == {
            self.group1.id, self.group2.id
        }

    def test_doctor_org_boundary_validation(self):
        """Verify assigning a Doctor to a CourseOffering in another organization fails."""
        other_org = OrganizationFactory()
        other_course = CourseFactory(organization=other_org)
        other_offering = CourseOfferingFactory(course=other_course, doctor=None)

        other_offering.doctor = self.doctor
        with pytest.raises(ValidationError) as exc_info:
            other_offering.clean()

        assert 'doctor' in exc_info.value.message_dict

    def test_ta_org_boundary_validation(self):
        """Verify assigning a TA to a Group in another organization fails."""
        other_org = OrganizationFactory()
        other_course = CourseFactory(organization=other_org)
        other_offering = CourseOfferingFactory(course=other_course)
        other_group = GroupFactory(course_offering=other_offering, teaching_assistant=None)

        other_group.teaching_assistant = self.ta
        with pytest.raises(ValidationError) as exc_info:
            other_group.clean()

        assert 'teaching_assistant' in exc_info.value.message_dict

    def test_schedule_group_mismatch_rejected(self):
        """Verify Schedule with group from offering B and offering A raises ValidationError."""
        schedule = Schedule(
            course_offering=self.offering1,
            group=self.group2,  # group2 belongs to offering2!
            session_type='LAB',
            day_of_week=1,
            start_time='08:00:00',
            end_time='10:00:00',
        )
        with pytest.raises(ValidationError) as exc_info:
            schedule.clean()

        assert 'group' in exc_info.value.message_dict

    def test_bulk_assign_courses_to_doctor_api(self):
        """Test bulk assigning course offerings to a doctor via REST API."""
        url = f'/api/v1/staff/doctors/{self.doctor.id}/assign-courses/'
        payload = {'course_offering_ids': [self.offering1.id, self.offering2.id]}
        res = self.client.post(url, payload, format='json')
        assert res.status_code == status.HTTP_200_OK
        assert len(res.data['assigned_course_offerings']) == 2

    def test_bulk_assign_groups_to_ta_api(self):
        """Test bulk assigning lab groups to a TA via REST API."""
        url = f'/api/v1/staff/assistants/{self.ta.id}/assign-groups/'
        payload = {'group_ids': [self.group1.id, self.group2.id]}
        res = self.client.post(url, payload, format='json')
        assert res.status_code == status.HTTP_200_OK
        assert len(res.data['assigned_groups']) == 2

    def test_doctor_schedules_api(self):
        """Test retrieving all schedules for course offerings led by a Doctor."""
        ScheduleFactory(course_offering=self.offering1, session_type='LECTURE', day_of_week=0)
        ScheduleFactory(course_offering=self.offering2, session_type='LECTURE', day_of_week=2)

        url = f'/api/v1/staff/doctors/{self.doctor.id}/schedules/'
        res = self.client.get(url)
        assert res.status_code == status.HTTP_200_OK
        assert res.data['count'] == 2

    def test_ta_schedules_api(self):
        """Test retrieving all schedules for groups assigned to a TA."""
        ScheduleFactory(course_offering=self.offering1, group=self.group1, session_type='LAB', day_of_week=1)
        ScheduleFactory(course_offering=self.offering2, group=self.group2, session_type='LAB', day_of_week=3)

        url = f'/api/v1/staff/assistants/{self.ta.id}/schedules/'
        res = self.client.get(url)
        assert res.status_code == status.HTTP_200_OK
        assert res.data['count'] == 2
