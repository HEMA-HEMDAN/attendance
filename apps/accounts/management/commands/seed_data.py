from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from apps.organizations.models import Organization, OrganizationStatus
from apps.accounts.models import User, Role
from apps.groups.models import Group, GroupStatus
from apps.students.models import Student, StudentStatus
from apps.teachers.models import Teacher
from apps.courses.models import Course, CourseStatus
from apps.locations.models import AttendanceLocation, LocationStatus
from apps.attendance.models import AttendanceSession, SessionStatus


class Command(BaseCommand):
    help = 'Seeds initial test/demo data for Bio Attendance system'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Seeding demo data...'))

        # 1. Organization
        org, _ = Organization.objects.get_or_create(
            slug='tech-uni',
            defaults={'name': 'Tech University', 'status': OrganizationStatus.ACTIVE}
        )

        # 2. Users
        # Admin
        admin_user, created = User.objects.get_or_create(
            email='admin@techuni.edu',
            defaults={
                'first_name': 'Admin',
                'last_name': 'User',
                'role': Role.ADMIN,
                'organization': org,
                'is_staff': True,
                'is_superuser': True,
            }
        )
        if created:
            admin_user.set_password('AdminPass123!')
            admin_user.save()

        # Doctor
        doctor_user, created = User.objects.get_or_create(
            email='doctor@techuni.edu',
            defaults={
                'first_name': 'Sarah',
                'last_name': 'Connor',
                'role': Role.DOCTOR,
                'organization': org,
            }
        )
        if created:
            doctor_user.set_password('DoctorPass123!')
            doctor_user.save()

        doctor_profile, _ = Teacher.objects.get_or_create(
            user=doctor_user,
            defaults={'organization': org}
        )
        
        # Teaching Assistant
        ta_user, created = User.objects.get_or_create(
            email='ta@techuni.edu',
            defaults={
                'first_name': 'Mark',
                'last_name': 'Johnson',
                'role': Role.TEACHING_ASSISTANT,
                'organization': org,
            }
        )
        if created:
            ta_user.set_password('TaPass123!')
            ta_user.save()

        ta_profile, _ = Teacher.objects.get_or_create(
            user=ta_user,
            defaults={'organization': org}
        )

        # Student 1
        student_user1, created = User.objects.get_or_create(
            email='student@techuni.edu',
            defaults={
                'first_name': 'John',
                'last_name': 'Doe',
                'role': Role.STUDENT,
                'organization': org,
            }
        )
        if created:
            student_user1.set_password('StudentPass123!')
            student_user1.save()

        # Student 2
        student_user2, created = User.objects.get_or_create(
            email='student2@techuni.edu',
            defaults={
                'first_name': 'Alice',
                'last_name': 'Smith',
                'role': Role.STUDENT,
                'organization': org,
            }
        )
        if created:
            student_user2.set_password('StudentPass123!')
            student_user2.save()

        # 3. Group
        group, _ = Group.objects.get_or_create(
            organization=org,
            name='CS-101 Class A',
            defaults={
                'status': GroupStatus.ACTIVE,
                'teaching_assistant': ta_profile
            }
        )
        group.teaching_assistant = ta_profile
        group.save()

        # Student Profiles
        student_profile1, _ = Student.objects.get_or_create(
            user=student_user1,
            defaults={
                'organization': org,
                'student_id': 'STU-1001',
                'group': group,
                'department': 'Computer Science',
                'academic_level': 1,
                'status': StudentStatus.ACTIVE,
            }
        )
        if student_profile1.group != group:
            student_profile1.group = group
            student_profile1.save()

        student_profile2, _ = Student.objects.get_or_create(
            user=student_user2,
            defaults={
                'organization': org,
                'student_id': 'STU-1002',
                'group': group,
                'department': 'Computer Science',
                'academic_level': 1,
                'status': StudentStatus.ACTIVE,
            }
        )
        if student_profile2.group != group:
            student_profile2.group = group
            student_profile2.save()

        # 4. Course
        course, _ = Course.objects.get_or_create(
            organization=org,
            code='CS301',
            defaults={
                'name': 'Mobile App Development',
                'teacher': doctor_profile,
                'academic_year': '2026-2027',
                'semester': 1,
                'department': 'Computer Science',
                'level': 3,
                'status': CourseStatus.ACTIVE,
            }
        )
        course.groups.add(group)

        # 6. Active Session
        now = timezone.now()
        expires = now + timedelta(hours=2)

        session, created = AttendanceSession.objects.get_or_create(
            organization=org,
            course=course,
            status=SessionStatus.ACTIVE,
            defaults={
                'teacher': doctor_profile,
                'session_type': 'LECTURE',
                'latitude': 30.0444210,
                'longitude': 31.2357120,
                'radius_meters': 500,
                'starts_at': now,
                'expires_at': expires,
                'biometric_required': True,
                'location_required': True,
                'late_after_minutes': 15,
                'duration_minutes': 120,
            }
        )
        if not created and session.expires_at < now:
            session.expires_at = expires
            session.status = SessionStatus.ACTIVE
            session.save()

        self.stdout.write(self.style.SUCCESS('\nSuccessfully seeded demo data!'))
        self.stdout.write(self.style.SUCCESS('============================================='))
        self.stdout.write(self.style.SUCCESS('Credentials for testing:'))
        self.stdout.write(self.style.SUCCESS('  Student 1 : student@techuni.edu / StudentPass123!'))
        self.stdout.write(self.style.SUCCESS('  Student 2 : student2@techuni.edu / StudentPass123!'))
        self.stdout.write(self.style.SUCCESS('  Doctor    : doctor@techuni.edu / DoctorPass123!'))
        self.stdout.write(self.style.SUCCESS('  TA        : ta@techuni.edu / TaPass123!'))
        self.stdout.write(self.style.SUCCESS('  Admin     : admin@techuni.edu   / AdminPass123!'))
        self.stdout.write(self.style.SUCCESS('============================================='))
