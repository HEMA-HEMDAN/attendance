"""
Shared test factories using factory_boy.
"""

import factory
from factory.django import DjangoModelFactory
from django.utils import timezone
from datetime import timedelta

from apps.accounts.models import User, Role
from apps.organizations.models import Organization
from apps.groups.models import Group
from apps.students.models import Student
from apps.teachers.models import Teacher
from apps.courses.models import Course
from apps.devices.models import Device
from apps.locations.models import AttendanceLocation
from apps.attendance.models import AttendanceSession


class OrganizationFactory(DjangoModelFactory):
    class Meta:
        model = Organization

    name = factory.Sequence(lambda n: f'Organization {n}')
    slug = factory.Sequence(lambda n: f'org-{n}')
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

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        return User.objects.create_user(password='testpass123', **kwargs)


class TeacherUserFactory(DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f'teacher{n}@example.com')
    first_name = 'Teacher'
    last_name = factory.Sequence(lambda n: f'User{n}')
    role = Role.DOCTOR
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


class GroupFactory(DjangoModelFactory):
    class Meta:
        model = Group

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f'Group {n}')
    status = 'ACTIVE'


class TeacherFactory(DjangoModelFactory):
    class Meta:
        model = Teacher

    user = factory.SubFactory(TeacherUserFactory)
    organization = factory.LazyAttribute(lambda o: o.user.organization)


class StudentFactory(DjangoModelFactory):
    class Meta:
        model = Student

    user = factory.SubFactory(StudentUserFactory)
    organization = factory.LazyAttribute(lambda o: o.user.organization)
    student_id = factory.Sequence(lambda n: f'STU{n:06d}')
    group = factory.SubFactory(GroupFactory, organization=factory.SelfAttribute('..organization'))
    status = 'ACTIVE'


class CourseFactory(DjangoModelFactory):
    class Meta:
        model = Course

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f'Course {n}')
    code = factory.Sequence(lambda n: f'CRS{n:03d}')
    teacher = factory.SubFactory(TeacherFactory, organization=factory.SelfAttribute('..organization'))
    status = 'ACTIVE'


class AttendanceLocationFactory(DjangoModelFactory):
    class Meta:
        model = AttendanceLocation

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f'Location {n}')
    latitude = '24.7136'
    longitude = '46.6753'
    radius_meters = 150
    status = 'ACTIVE'


class AttendanceSessionFactory(DjangoModelFactory):
    class Meta:
        model = AttendanceSession

    organization = factory.SubFactory(OrganizationFactory)
    course = factory.SubFactory(CourseFactory, organization=factory.SelfAttribute('..organization'))
    group = factory.SubFactory(GroupFactory, organization=factory.SelfAttribute('..organization'))
    teacher = factory.SubFactory(TeacherFactory, organization=factory.SelfAttribute('..organization'))
    location = factory.SubFactory(AttendanceLocationFactory, organization=factory.SelfAttribute('..organization'))
    status = 'ACTIVE'
    starts_at = factory.LazyFunction(timezone.now)
    expires_at = factory.LazyFunction(lambda: timezone.now() + timedelta(hours=1))
    biometric_required = True
    location_required = True
    late_after_minutes = 15
    duration_minutes = 60
