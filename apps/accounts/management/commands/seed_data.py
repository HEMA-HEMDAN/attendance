from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from apps.organizations.models import Organization, OrganizationStatus
from apps.accounts.models import User, Role
from apps.groups.models import Group, GroupStatus
from apps.students.models import Student, StudentStatus, StudentEnrollment
from apps.teachers.models import Teacher
from apps.courses.models import Course, CourseStatus
from apps.locations.models import AttendanceLocation, LocationStatus
from apps.attendance.models import AttendanceSession, SessionStatus


class Command(BaseCommand):
    help = 'Seeds initial test/demo data for Bio Attendance system'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Seeding demo data...'))

        org, _ = Organization.objects.get_or_create(
            slug='tech-uni',
            defaults={'name': 'Tech University', 'status': OrganizationStatus.ACTIVE}
        )

        def create_user(email, first, last, role, is_admin=False):
            u, created = User.objects.get_or_create(
                email=email,
                defaults={
                    'first_name': first,
                    'last_name': last,
                    'role': role,
                    'organization': org,
                    'is_staff': is_admin,
                    'is_superuser': is_admin,
                }
            )
            if created:
                u.set_password('Pass123!')
                u.save()
            return u

        # Users
        admin_user = create_user('admin@techuni.edu', 'Admin', 'User', Role.ADMIN, True)
        
        doc_cs301 = create_user('doc301@techuni.edu', 'Sarah', 'Connor', Role.DOCTOR)
        doc_cs401 = create_user('doc401@techuni.edu', 'Alan', 'Turing', Role.DOCTOR)
        
        ta_mark = create_user('ta_mark@techuni.edu', 'Mark', 'Johnson', Role.TEACHING_ASSISTANT)
        ta_lucy = create_user('ta_lucy@techuni.edu', 'Lucy', 'Smith', Role.TEACHING_ASSISTANT)
        
        stu1_user = create_user('student1@techuni.edu', 'John', 'Doe', Role.STUDENT)
        stu2_user = create_user('student2@techuni.edu', 'Alice', 'Wonderland', Role.STUDENT)

        # Teachers
        t_doc301, _ = Teacher.objects.get_or_create(user=doc_cs301, defaults={'organization': org})
        t_doc401, _ = Teacher.objects.get_or_create(user=doc_cs401, defaults={'organization': org})
        t_ta_mark, _ = Teacher.objects.get_or_create(user=ta_mark, defaults={'organization': org})
        t_ta_lucy, _ = Teacher.objects.get_or_create(user=ta_lucy, defaults={'organization': org})

        # Groups (Labs)
        g_cs301_l1, _ = Group.objects.get_or_create(organization=org, name='CS301-Lab1', defaults={'teaching_assistant': t_ta_mark})
        g_cs301_l1.teaching_assistant = t_ta_mark
        g_cs301_l1.save()

        g_cs301_l2, _ = Group.objects.get_or_create(organization=org, name='CS301-Lab2', defaults={'teaching_assistant': t_ta_lucy})
        g_cs301_l2.teaching_assistant = t_ta_lucy
        g_cs301_l2.save()

        g_cs401_l1, _ = Group.objects.get_or_create(organization=org, name='CS401-Lab1', defaults={'teaching_assistant': t_ta_mark})
        g_cs401_l1.teaching_assistant = t_ta_mark
        g_cs401_l1.save()

        # Courses
        c_cs301, _ = Course.objects.get_or_create(
            organization=org, code='CS301',
            defaults={'name': 'Mobile App Dev', 'teacher': t_doc301, 'department': 'CS', 'level': '3'}
        )
        c_cs301.groups.add(g_cs301_l1, g_cs301_l2)
        
        c_cs401, _ = Course.objects.get_or_create(
            organization=org, code='CS401',
            defaults={'name': 'Artificial Intelligence', 'teacher': t_doc401, 'department': 'CS', 'level': '4'}
        )
        c_cs401.groups.add(g_cs401_l1)

        # Students
        stu1, _ = Student.objects.get_or_create(
            user=stu1_user, defaults={'organization': org, 'student_id': 'STU-1001', 'department': 'CS', 'academic_level': '3'}
        )
        stu2, _ = Student.objects.get_or_create(
            user=stu2_user, defaults={'organization': org, 'student_id': 'STU-1002', 'department': 'CS', 'academic_level': '3'}
        )

        # Enrollments
        # stu1: takes CS301 (Lab 1) and CS401 (Lab 1)
        StudentEnrollment.objects.get_or_create(student=stu1, course=c_cs301, defaults={'group': g_cs301_l1})
        StudentEnrollment.objects.get_or_create(student=stu1, course=c_cs401, defaults={'group': g_cs401_l1})
        
        # stu2: takes CS301 (Lab 2)
        StudentEnrollment.objects.get_or_create(student=stu2, course=c_cs301, defaults={'group': g_cs301_l2})

        # Active Sessions
        now = timezone.now()
        expires = now + timedelta(hours=2)

        # 1. Lecture for CS301 (No group, both students should see it)
        session_lec, _ = AttendanceSession.objects.get_or_create(
            organization=org, course=c_cs301, group=None, name='Intro to React Native',
            defaults={
                'teacher': t_doc301, 'session_type': 'LECTURE',
                'status': SessionStatus.ACTIVE, 'starts_at': now, 'expires_at': expires,
                'latitude': 30.0444, 'longitude': 31.2357, 'radius_meters': 500,
                'duration_minutes': 120,
            }
        )
        if session_lec.expires_at < now:
            session_lec.expires_at = expires
            session_lec.status = SessionStatus.ACTIVE
            session_lec.save()

        # 2. Lab for CS301-Lab2 (Only Student 2 should see it)
        session_lab, _ = AttendanceSession.objects.get_or_create(
            organization=org, course=c_cs301, group=g_cs301_l2, name='Lab Assignment 1',
            defaults={
                'teacher': t_ta_lucy, 'session_type': 'LAB',
                'status': SessionStatus.ACTIVE, 'starts_at': now, 'expires_at': expires,
                'latitude': 30.0444, 'longitude': 31.2357, 'radius_meters': 100,
                'duration_minutes': 120,
            }
        )
        if session_lab.expires_at < now:
            session_lab.expires_at = expires
            session_lab.status = SessionStatus.ACTIVE
            session_lab.save()

        self.stdout.write(self.style.SUCCESS('\nSuccessfully seeded demo data!'))
        self.stdout.write(self.style.SUCCESS('All passwords are: Pass123!'))
        self.stdout.write(self.style.SUCCESS('Users:'))
        self.stdout.write(self.style.SUCCESS('  student1@techuni.edu (CS301 Lab1, CS401 Lab1)'))
        self.stdout.write(self.style.SUCCESS('  student2@techuni.edu (CS301 Lab2)'))
        self.stdout.write(self.style.SUCCESS('  doc301@techuni.edu'))
        self.stdout.write(self.style.SUCCESS('  doc401@techuni.edu'))
        self.stdout.write(self.style.SUCCESS('  ta_mark@techuni.edu'))
        self.stdout.write(self.style.SUCCESS('  ta_lucy@techuni.edu'))
        self.stdout.write(self.style.SUCCESS('  admin@techuni.edu'))

