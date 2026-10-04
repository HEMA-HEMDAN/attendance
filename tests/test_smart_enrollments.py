import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient
from rest_framework import status
from tests.factories import (
    OrganizationFactory, AdminUserFactory, StudentFactory, CourseFactory,
    CourseOfferingFactory, GroupFactory, AcademicYearFactory, SemesterFactory,
)
from apps.students.models import StudentEnrollment


@pytest.mark.django_db
class TestSmartStudentEnrollments:
    def setup_method(self):
        self.org = OrganizationFactory()
        self.admin_user = AdminUserFactory(organization=self.org)
        self.student = StudentFactory(organization=self.org)

        self.ay = AcademicYearFactory(organization=self.org)
        self.sem = SemesterFactory(organization=self.org, academic_year=self.ay)

        self.course1 = CourseFactory(organization=self.org, code='CS101')
        self.course2 = CourseFactory(organization=self.org, code='CS102')

        self.offering1 = CourseOfferingFactory(course=self.course1, academic_year=self.ay, semester=self.sem)
        self.offering2 = CourseOfferingFactory(course=self.course2, academic_year=self.ay, semester=self.sem)

        self.group1 = GroupFactory(course_offering=self.offering1, name='Section 1')
        self.group2 = GroupFactory(course_offering=self.offering2, name='Section 2')

        self.client = APIClient()
        self.client.force_authenticate(user=self.admin_user)

    def test_student_can_have_multiple_course_enrollments(self):
        """Verify that a student can be enrolled in multiple distinct course offerings."""
        enrollment1 = StudentEnrollment.objects.create(
            student=self.student,
            course_offering=self.offering1,
            group=self.group1,
        )
        enrollment2 = StudentEnrollment.objects.create(
            student=self.student,
            course_offering=self.offering2,
            group=self.group2,
        )

        assert self.student.enrollments.count() == 2
        assert set(self.student.enrollments.values_list('course_offering_id', flat=True)) == {
            self.offering1.id, self.offering2.id
        }

    def test_group_relevance_validation_rejected_on_mismatch(self):
        """Verify that assigning a group from Offering B to an enrollment in Offering A raises ValidationError."""
        enrollment = StudentEnrollment(
            student=self.student,
            course_offering=self.offering1,
            group=self.group2,  # group2 belongs to offering2!
        )
        with pytest.raises(ValidationError) as exc_info:
            enrollment.clean()

        assert 'group' in exc_info.value.message_dict

    def test_organization_boundary_validation_rejected(self):
        """Verify that enrolling a student into a course offering of another organization raises ValidationError."""
        other_org = OrganizationFactory()
        other_course = CourseFactory(organization=other_org)
        other_offering = CourseOfferingFactory(course=other_course)

        enrollment = StudentEnrollment(
            student=self.student,
            course_offering=other_offering,
        )
        with pytest.raises(ValidationError) as exc_info:
            enrollment.clean()

        assert 'course_offering' in exc_info.value.message_dict

    def test_duplicate_enrollment_same_course_offering_rejected(self):
        """Verify duplicate enrollment in the exact same course offering is rejected."""
        StudentEnrollment.objects.create(
            student=self.student,
            course_offering=self.offering1,
            group=self.group1,
        )

        duplicate = StudentEnrollment(
            student=self.student,
            course_offering=self.offering1,
            group=self.group1,
        )
        with pytest.raises(Exception):
            duplicate.save()

    def test_bulk_enrollment_api_success(self):
        """Test bulk enrolling a student in multiple course offerings via REST API."""
        url = f'/api/v1/students/{self.student.id}/bulk-enroll/'
        payload = {
            'enrollments': [
                {'course_offering_id': self.offering1.id, 'group_id': self.group1.id},
                {'course_offering_id': self.offering2.id, 'group_id': self.group2.id},
            ]
        }
        res = self.client.post(url, payload, format='json')
        assert res.status_code == status.HTTP_201_CREATED
        assert len(res.data) == 2
        assert self.student.enrollments.count() == 2

    def test_bulk_enrollment_api_group_mismatch_rejected(self):
        """Test bulk enrollment fails atomically if any item passes a mismatched group."""
        url = f'/api/v1/students/{self.student.id}/bulk-enroll/'
        payload = {
            'enrollments': [
                {'course_offering_id': self.offering1.id, 'group_id': self.group2.id},  # Mismatch!
            ]
        }
        res = self.client.post(url, payload, format='json')
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert self.student.enrollments.count() == 0
