"""
Academic Hierarchy & Boundary Tests.
Covers AcademicYear, Semester, CourseOffering, Group, and StudentEnrollment edge cases.
"""

import pytest
from datetime import date
from django.db import IntegrityError
from rest_framework.test import APIClient

from tests.factories import (
    OrganizationFactory, AdminUserFactory, DoctorFactory, TeachingAssistantFactory,
    StudentFactory, AcademicYearFactory, SemesterFactory, CourseFactory,
    CourseOfferingFactory, GroupFactory, StudentEnrollmentFactory,
)


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestAcademicBoundaries:
    def test_academic_year_date_range(self):
        org = OrganizationFactory()
        year = AcademicYearFactory(organization=org, start_date=date(2026, 9, 1), end_date=date(2027, 6, 30))
        assert year.start_date < year.end_date

    def test_semester_within_academic_year(self):
        org = OrganizationFactory()
        year = AcademicYearFactory(organization=org, start_date=date(2026, 9, 1), end_date=date(2027, 6, 30))
        sem_fall = SemesterFactory(academic_year=year, name='Fall', start_date=date(2026, 9, 1), end_date=date(2026, 12, 31))
        sem_spring = SemesterFactory(academic_year=year, name='Spring', start_date=date(2027, 1, 15), end_date=date(2027, 5, 30))

        assert sem_fall.academic_year == year
        assert sem_spring.academic_year == year

    def test_historical_course_offering_separation(self):
        org = OrganizationFactory()
        course = CourseFactory(organization=org, code='CS304', name='Database Systems')

        year_26 = AcademicYearFactory(organization=org, name='2026/2027')
        sem_fall_26 = SemesterFactory(academic_year=year_26, name='Fall')

        year_27 = AcademicYearFactory(organization=org, name='2027/2028')
        sem_fall_27 = SemesterFactory(academic_year=year_27, name='Fall')

        offering_1 = CourseOfferingFactory(course=course, academic_year=year_26, semester=sem_fall_26)
        offering_2 = CourseOfferingFactory(course=course, academic_year=year_27, semester=sem_fall_27)

        assert offering_1.id != offering_2.id
        assert offering_1.course == offering_2.course

    def test_duplicate_course_offering_rejected(self):
        org = OrganizationFactory()
        course = CourseFactory(organization=org)
        year = AcademicYearFactory(organization=org)
        sem = SemesterFactory(academic_year=year)

        CourseOfferingFactory(course=course, academic_year=year, semester=sem)
        with pytest.raises(Exception):
            CourseOfferingFactory(course=course, academic_year=year, semester=sem)

    def test_duplicate_student_enrollment_rejected(self):
        student = StudentFactory()
        offering = CourseOfferingFactory()
        StudentEnrollmentFactory(student=student, course_offering=offering)

        with pytest.raises(Exception):
            StudentEnrollmentFactory(student=student, course_offering=offering)
