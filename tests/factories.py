"""
Shared test factories using factory_boy for the updated date-driven attendance system.
"""

import factory
from factory.django import DjangoModelFactory
from django.utils import timezone
from datetime import timedelta, date

from apps.accounts.models import User, Role
from apps.organizations.models import Organization
from apps.staff.models import Doctor, TeachingAssistant
from apps.courses.models import AcademicYear, Semester, Course, CourseOffering, Schedule
from apps.groups.models import Group
from apps.students.models import Student, StudentEnrollment
from apps.locations.models import AttendanceLocation
from apps.attendance.models import SessionOccurrence, AttendanceSession


class OrganizationFactory(DjangoModelFactory):
    class Meta:
        model = Organization

    name = factory.Sequence(lambda n: f'Organization {n}')
    slug = factory.Sequence(lambda n: f'org-{n}')
    timezone = 'Africa/Cairo'
    status = 'ACTIVE'


class AdminUserFactory(DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f'admin{n}@example.com')
    first_name = 'Admin'
    last_name = factory.Sequence(lambda n: f'User{n}')
    role = Role.ADMIN
    organization = factory.SubFactory(OrganizationFactory)
    is_active = True
    is_staff = True

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        return User.objects.create_user(password='testpass123', **kwargs)


class DoctorUserFactory(DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f'doctor{n}@example.com')
    first_name = 'Doctor'
    last_name = factory.Sequence(lambda n: f'User{n}')
    role = Role.DOCTOR
    organization = factory.SubFactory(OrganizationFactory)
    is_active = True

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        return User.objects.create_user(password='testpass123', **kwargs)


class TAUserFactory(DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f'ta{n}@example.com')
    first_name = 'TA'
    last_name = factory.Sequence(lambda n: f'User{n}')
    role = Role.TEACHING_ASSISTANT
    organization = factory.SubFactory(OrganizationFactory)
    is_active = True

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        return User.objects.create_user(password='testpass123', **kwargs)


class StudentUserFactory(DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f'student{n}@example.com')
    first_name = 'Student'
    last_name = factory.Sequence(lambda n: f'User{n}')
    role = Role.STUDENT
    organization = factory.SubFactory(OrganizationFactory)
    is_active = True

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        return User.objects.create_user(password='testpass123', **kwargs)


class DoctorFactory(DjangoModelFactory):
    class Meta:
        model = Doctor

    user = factory.SubFactory(DoctorUserFactory)
    organization = factory.LazyAttribute(lambda o: o.user.organization)
    title = 'Dr.'


class TeachingAssistantFactory(DjangoModelFactory):
    class Meta:
        model = TeachingAssistant

    user = factory.SubFactory(TAUserFactory)
    organization = factory.LazyAttribute(lambda o: o.user.organization)


class StudentFactory(DjangoModelFactory):
    class Meta:
        model = Student

    user = factory.SubFactory(StudentUserFactory)
    organization = factory.LazyAttribute(lambda o: o.user.organization)
    student_id = factory.Sequence(lambda n: f'STU{n:06d}')
    status = 'ACTIVE'


class AcademicYearFactory(DjangoModelFactory):
    class Meta:
        model = AcademicYear

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f'202{n}/202{n+1}')
    start_date = date(2026, 9, 1)
    end_date = date(2027, 6, 30)
    is_active = True


class SemesterFactory(DjangoModelFactory):
    class Meta:
        model = Semester

    organization = factory.LazyAttribute(lambda o: o.academic_year.organization)
    academic_year = factory.SubFactory(AcademicYearFactory)
    name = 'Fall'
    start_date = date(2026, 9, 1)
    end_date = date(2026, 12, 31)
    is_active = True


class CourseFactory(DjangoModelFactory):
    class Meta:
        model = Course

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f'Course {n}')
    code = factory.Sequence(lambda n: f'CRS{n:03d}')


class CourseOfferingFactory(DjangoModelFactory):
    class Meta:
        model = CourseOffering

    course = factory.SubFactory(CourseFactory)
    academic_year = factory.SubFactory(AcademicYearFactory, organization=factory.SelfAttribute('..course.organization'))
    semester = factory.SubFactory(SemesterFactory, academic_year=factory.SelfAttribute('..academic_year'))
    doctor = factory.SubFactory(DoctorFactory, organization=factory.SelfAttribute('..course.organization'))
    status = 'ACTIVE'


class GroupFactory(DjangoModelFactory):
    class Meta:
        model = Group

    course_offering = factory.SubFactory(CourseOfferingFactory)
    name = factory.Sequence(lambda n: f'Group {n}')
    teaching_assistant = factory.SubFactory(TeachingAssistantFactory, organization=factory.SelfAttribute('..course_offering.course.organization'))
    status = 'ACTIVE'


class StudentEnrollmentFactory(DjangoModelFactory):
    class Meta:
        model = StudentEnrollment

    student = factory.SubFactory(StudentFactory)
    course_offering = factory.SubFactory(CourseOfferingFactory)
    group = factory.SubFactory(GroupFactory, course_offering=factory.SelfAttribute('..course_offering'))


class ScheduleFactory(DjangoModelFactory):
    class Meta:
        model = Schedule

    course_offering = factory.SubFactory(CourseOfferingFactory)
    group = None
    session_type = 'LECTURE'
    day_of_week = 2  # Wednesday
    start_time = '10:00:00'
    end_time = '12:00:00'
    is_active = True


class AttendanceLocationFactory(DjangoModelFactory):
    class Meta:
        model = AttendanceLocation

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f'Location {n}')
    latitude = '24.7136'
    longitude = '46.6753'
    radius_meters = 150
    status = 'ACTIVE'


class SessionOccurrenceFactory(DjangoModelFactory):
    class Meta:
        model = SessionOccurrence

    schedule = factory.SubFactory(ScheduleFactory)
    course_offering = factory.LazyAttribute(lambda o: o.schedule.course_offering)
    group = factory.LazyAttribute(lambda o: o.schedule.group)
    scheduled_date = date.today()
    starts_at = factory.LazyFunction(timezone.now)
    ends_at = factory.LazyFunction(lambda: timezone.now() + timedelta(hours=1))
    session_type = 'LECTURE'
    status = 'SCHEDULED'


class AttendanceSessionFactory(DjangoModelFactory):
    class Meta:
        model = AttendanceSession

    occurrence = factory.SubFactory(SessionOccurrenceFactory)
    organization = factory.LazyAttribute(lambda o: o.occurrence.course_offering.course.organization)
    opened_by = factory.LazyAttribute(lambda o: o.occurrence.course_offering.doctor.user)
    latitude = 24.7136
    longitude = 46.6753
    radius_meters = 50.0
    status = 'ACTIVE'
    starts_at = factory.LazyFunction(timezone.now)
    expires_at = factory.LazyFunction(lambda: timezone.now() + timedelta(hours=1))
