from datetime import date, datetime, time, timedelta
import zoneinfo

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Role, User
from apps.accounts.admin_permissions import configure_organization_admin
from apps.attendance.models import (
    AttendanceRecord,
    AttendanceSession,
    SessionOccurrence,
    SessionOccurrenceStatus,
    SessionStatus,
)
from apps.attendance.services import sync_today_occurrences
from apps.courses.models import (
    AcademicYear,
    Course,
    CourseOffering,
    ExceptionType,
    Schedule,
    ScheduleException,
    Semester,
    SessionType,
)
from apps.groups.models import Group, GroupStatus
from apps.locations.models import AttendanceLocation, LocationStatus
from apps.organizations.models import Organization, OrganizationStatus
from apps.staff.models import Doctor, TeachingAssistant
from apps.students.models import Student, StudentEnrollment, StudentStatus


class Command(BaseCommand):
    help = 'Seeds idempotent development data for the finalized university attendance domain.'

    password = 'Pass123!'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Seeding Tech University demo data...'))
        with transaction.atomic():
            data = self._seed()
        self._print_summary(data)

    def _seed(self):
        organization, _ = Organization.objects.update_or_create(
            slug='tech-uni',
            defaults={
                'name': 'Tech University',
                'timezone': 'Africa/Cairo',
                'status': OrganizationStatus.ACTIVE,
            },
        )
        org_tz = zoneinfo.ZoneInfo(organization.timezone)
        today = datetime.now(tz=org_tz).date()

        superadmin = self._user(
            'superadmin@demo.local', 'Platform', 'Superadmin', Role.SUPERADMIN,
            organization=None, is_staff=True, is_superuser=True,
        )
        admin = self._user(
            'admin@techuni.edu', 'University', 'Admin', Role.ADMIN,
            organization=organization, is_staff=True,
        )
        configure_organization_admin(admin)

        doctors = {
            'doctor1': self._doctor('doctor1@techuni.edu', 'Sarah', 'Connor', organization, 'Computer Science', 'Dr.'),
            'doctor2': self._doctor('doctor2@techuni.edu', 'Alan', 'Turing', organization, 'Computer Science', 'Prof.'),
        }
        assistants = {
            'ta1': self._assistant('ta1@techuni.edu', 'Mark', 'Johnson', organization, 'Computer Science'),
            'ta2': self._assistant('ta2@techuni.edu', 'Lucy', 'Smith', organization, 'Computer Science'),
        }

        academic_year = self._academic_year(organization, today)
        semester = self._semester(organization, academic_year)
        location = self._location(organization)
        courses = self._courses(organization)
        offerings = self._offerings(courses, academic_year, semester, doctors)
        groups = self._groups(offerings, assistants)
        schedules = self._schedules(offerings, groups, location, academic_year, today)
        students = self._students(organization)
        enrollments = self._enrollments(students, offerings, groups)
        self._exceptions(schedules, today)

        # The service is the source of truth for today's occurrence generation.
        today_occurrences = sync_today_occurrences(organization)
        occurrences = self._future_and_historical_occurrences(
            schedules, offerings, groups, today_occurrences, org_tz, today,
        )
        historical_session = self._historical_session(
            occurrences['historical'], organization, doctors['doctor1'].user, org_tz,
        )
        self._historical_records(historical_session, students)

        return {
            'organization': organization,
            'superadmin': superadmin,
            'admin': admin,
            'doctors': doctors,
            'assistants': assistants,
            'academic_year': academic_year,
            'semester': semester,
            'courses': courses,
            'groups': groups,
            'students': students,
            'enrollments': enrollments,
            'occurrences': occurrences,
            'historical_session': historical_session,
        }

    def _user(self, email, first_name, last_name, role, organization=None, is_staff=False, is_superuser=False):
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                'first_name': first_name,
                'last_name': last_name,
                'role': role,
                'organization': organization,
                'is_staff': is_staff,
                'is_superuser': is_superuser,
            },
        )
        changed = []
        for field, value in {
            'first_name': first_name,
            'last_name': last_name,
            'role': role,
            'organization': organization,
            'is_staff': is_staff,
            'is_superuser': is_superuser,
            'is_active': True,
        }.items():
            if getattr(user, field) != value:
                setattr(user, field, value)
                changed.append(field)
        if created:
            user.set_password(self.password)
            changed.append('password')
        if changed:
            user.save(update_fields=changed)
        return user

    def _doctor(self, email, first_name, last_name, organization, department, title):
        user = self._user(email, first_name, last_name, Role.DOCTOR, organization)
        doctor, _ = Doctor.objects.update_or_create(
            user=user,
            defaults={'organization': organization, 'department': department, 'title': title},
        )
        return doctor

    def _assistant(self, email, first_name, last_name, organization, department):
        user = self._user(email, first_name, last_name, Role.TEACHING_ASSISTANT, organization)
        assistant, _ = TeachingAssistant.objects.update_or_create(
            user=user,
            defaults={'organization': organization, 'department': department},
        )
        return assistant

    def _academic_year(self, organization, today):
        start_year = today.year if today.month >= 8 else today.year - 1
        return AcademicYear.objects.update_or_create(
            organization=organization,
            name=f'{start_year}/{start_year + 1}',
            defaults={
                'start_date': date(start_year, 8, 1),
                'end_date': date(start_year + 1, 7, 31),
                'is_active': True,
            },
        )[0]

    def _semester(self, organization, academic_year):
        return Semester.objects.update_or_create(
            academic_year=academic_year,
            name='Fall',
            defaults={
                'organization': organization,
                'start_date': max(academic_year.start_date, date(academic_year.start_date.year, 9, 1)),
                'end_date': date(academic_year.start_date.year + 1, 1, 31),
                'is_active': True,
            },
        )[0]

    def _location(self, organization):
        return AttendanceLocation.objects.update_or_create(
            organization=organization,
            name='Main Campus',
            defaults={
                'latitude': 30.0444,
                'longitude': 31.2357,
                'radius_meters': 50,
                'status': LocationStatus.ACTIVE,
            },
        )[0]

    def _courses(self, organization):
        course_data = {
            'CS-304': ('Database Systems', 'Computer Science'),
            'CS-401': ('Artificial Intelligence', 'Computer Science'),
            'CS-302': ('Mobile Application Development', 'Computer Science'),
        }
        courses = {}
        for code, (name, department) in course_data.items():
            courses[code] = Course.objects.update_or_create(
                organization=organization,
                code=code,
                defaults={'name': name, 'department': department},
            )[0]
        return courses

    def _offerings(self, courses, academic_year, semester, doctors):
        doctor_map = {'CS-304': doctors['doctor1'], 'CS-401': doctors['doctor2'], 'CS-302': doctors['doctor1']}
        offerings = {}
        for code, course in courses.items():
            offerings[code] = CourseOffering.objects.update_or_create(
                course=course,
                academic_year=academic_year,
                semester=semester,
                defaults={'doctor': doctor_map[code], 'status': 'ACTIVE'},
            )[0]
        return offerings

    def _groups(self, offerings, assistants):
        group_data = {
            ('CS-304', 'Group A'): assistants['ta1'],
            ('CS-304', 'Group B'): assistants['ta2'],
            ('CS-401', 'Group A'): assistants['ta1'],
            ('CS-302', 'Group A'): assistants['ta2'],
        }
        groups = {}
        for (code, name), assistant in group_data.items():
            groups[(code, name)] = Group.objects.update_or_create(
                course_offering=offerings[code],
                name=name,
                defaults={'teaching_assistant': assistant, 'status': GroupStatus.ACTIVE},
            )[0]
        return groups

    def _schedules(self, offerings, groups, location, academic_year, today):
        end_date = academic_year.end_date
        schedule_data = {
            'cs304_lecture': (offerings['CS-304'], None, SessionType.LECTURE, 2, time(10, 0), time(12, 0)),
            'cs304_lab_a': (offerings['CS-304'], groups[('CS-304', 'Group A')], SessionType.LAB, 3, time(10, 0), time(12, 0)),
            'cs401_tutorial': (offerings['CS-401'], groups[('CS-401', 'Group A')], SessionType.TUTORIAL, 0, time(14, 0), time(16, 0)),
            'cs302_lab': (offerings['CS-302'], groups[('CS-302', 'Group A')], SessionType.LAB, 4, time(10, 0), time(12, 0)),
        }
        schedules = {}
        for key, (offering, group, session_type, weekday, start, end) in schedule_data.items():
            schedules[key] = Schedule.objects.update_or_create(
                course_offering=offering,
                group=group,
                session_type=session_type,
                day_of_week=weekday,
                defaults={
                    'location': location,
                    'start_time': start,
                    'end_time': end,
                    'effective_from': academic_year.start_date,
                    'effective_until': end_date,
                    'is_active': True,
                },
            )[0]
        return schedules

    def _students(self, organization):
        student_data = [
            ('student1@techuni.edu', 'John', 'Doe', 'STU-1001', '3'),
            ('student2@techuni.edu', 'Alice', 'Wonderland', 'STU-1002', '3'),
            ('student3@techuni.edu', 'Omar', 'Hassan', 'STU-1003', '3'),
            ('student4@techuni.edu', 'Maya', 'Nabil', 'STU-1004', '4'),
            ('student5@techuni.edu', 'Youssef', 'Kamal', 'STU-1005', '4'),
            ('student6@techuni.edu', 'Nour', 'Adel', 'STU-1006', '4'),
        ]
        students = {}
        for email, first, last, student_id, level in student_data:
            user = self._user(email, first, last, Role.STUDENT, organization)
            students[student_id] = Student.objects.update_or_create(
                user=user,
                defaults={
                    'organization': organization,
                    'student_id': student_id,
                    'department': 'Computer Science',
                    'academic_level': level,
                    'status': StudentStatus.ACTIVE,
                },
            )[0]
        return students

    def _enrollments(self, students, offerings, groups):
        enrollment_data = {
            'STU-1001': [('CS-304', 'Group A'), ('CS-401', 'Group A'), ('CS-302', 'Group A')],
            'STU-1002': [('CS-304', 'Group B'), ('CS-401', None)],
            'STU-1003': [('CS-304', 'Group A')],
            'STU-1004': [('CS-401', 'Group A'), ('CS-302', 'Group A')],
            'STU-1005': [('CS-304', 'Group B')],
            'STU-1006': [('CS-401', None), ('CS-302', 'Group A')],
        }
        enrollments = []
        for student_id, course_groups in enrollment_data.items():
            for code, group_name in course_groups:
                enrollment, _ = StudentEnrollment.objects.update_or_create(
                    student=students[student_id],
                    course_offering=offerings[code],
                    defaults={'group': groups[(code, group_name)] if group_name else None},
                )
                enrollments.append(enrollment)
        return enrollments

    def _exceptions(self, schedules, today):
        exception_date = today + timedelta(days=14)
        ScheduleException.objects.update_or_create(
            schedule=schedules['cs302_lab'],
            date=exception_date,
            defaults={
                'exception_type': ExceptionType.CANCELLED,
                'reason': 'Development example: lab cancelled for a university event.',
                'new_start_time': None,
                'new_end_time': None,
            },
        )

    def _future_and_historical_occurrences(self, schedules, offerings, groups, today_occurrences, org_tz, today):
        today_by_schedule = {occ.schedule_id: occ for occ in today_occurrences}
        next_thursday = self._next_weekday(today, 3)
        next_monday = self._next_weekday(today, 0)
        previous_wednesday = today - timedelta(days=(today.weekday() - 2) % 7 or 7)

        lab = self._ensure_occurrence(
            schedules['cs304_lab_a'], next_thursday, org_tz, SessionOccurrenceStatus.SCHEDULED,
        )
        tutorial = self._ensure_occurrence(
            schedules['cs401_tutorial'], next_monday, org_tz, SessionOccurrenceStatus.SCHEDULED,
        )
        historical = self._ensure_occurrence(
            schedules['cs304_lecture'], previous_wednesday, org_tz, SessionOccurrenceStatus.COMPLETED,
        )
        today_lecture = today_by_schedule.get(schedules['cs304_lecture'].id)
        if today_lecture is None:
            today_lecture = self._ensure_occurrence(
                schedules['cs304_lecture'], today, org_tz, SessionOccurrenceStatus.SCHEDULED,
            )
        return {'today_lecture': today_lecture, 'future_lab': lab, 'future_tutorial': tutorial, 'historical': historical}

    def _ensure_occurrence(self, schedule, scheduled_date, org_tz, status):
        starts_at = datetime.combine(
            scheduled_date,
            schedule.start_time,
            tzinfo=org_tz,
        )
        ends_at = datetime.combine(
            scheduled_date,
            schedule.end_time,
            tzinfo=org_tz,
        )

        occurrence, _ = SessionOccurrence.objects.update_or_create(
            schedule=schedule,
            scheduled_date=scheduled_date,
            defaults={
                'course_offering': schedule.course_offering,
                'group': schedule.group,
                'occurrence_type': 'SCHEDULED',
                'starts_at': starts_at,
                'ends_at': ends_at,
                'session_type': schedule.session_type,
                'status': status,
            },
        )

        return occurrence

    def _historical_session(self, occurrence, organization, opened_by, org_tz):
        starts_at = occurrence.starts_at
        expires_at = starts_at + timedelta(hours=2)

        return AttendanceSession.objects.update_or_create(
            occurrence=occurrence,
            defaults={
                'organization': organization,
                'opened_by': opened_by,
                'latitude': 30.0444,
                'longitude': 31.2357,
                'radius_meters': 50,
                'late_after_minutes': 15,
                'status': SessionStatus.CLOSED,
                'starts_at': starts_at,
                'expires_at': expires_at,
                'closed_at': expires_at,
            },
        )[0]

    def _historical_records(self, session, students):
        statuses = ['PRESENT', 'LATE', 'EXCUSED', 'CHEATING']
        for student, status in zip(list(students.values())[:4], statuses):
            AttendanceRecord.objects.update_or_create(
                session=session,
                student=student,
                defaults={
                    'status': status,
                    'submitted_latitude': 30.0444,
                    'submitted_longitude': 31.2357,
                    'location_accuracy_meters': 10,
                    'distance_from_location_meters': 20,
                    'mock_location_detected': False,
                    'device_challenge_verified': True,
                },
            )

    @staticmethod
    def _next_weekday(start_date, weekday):
        days_ahead = (weekday - start_date.weekday()) % 7
        return start_date + timedelta(days=days_ahead or 7)

    def _print_summary(self, data):
        occurrences = data['occurrences']
        self.stdout.write(self.style.SUCCESS('\nUniversity Attendance Demo Seed Complete'))
        self.stdout.write(f"Organization: {data['organization'].name} ({data['organization'].slug})")
        self.stdout.write(f"Academic year: {data['academic_year'].name} / Semester: {data['semester'].name}")
        self.stdout.write(f"Superadmin: {data['superadmin'].email}")
        self.stdout.write(f"Organization Admin: {data['admin'].email}")
        self.stdout.write('Doctors: ' + ', '.join(doctor.user.email for doctor in data['doctors'].values()))
        self.stdout.write('Teaching Assistants: ' + ', '.join(assistant.user.email for assistant in data['assistants'].values()))
        self.stdout.write(f"Students: {len(data['students'])} seeded")
        self.stdout.write('Courses: ' + ', '.join(course.code for course in data['courses'].values()))
        self.stdout.write('Occurrences:')
        for label, occurrence in occurrences.items():
            self.stdout.write(f'  {label}: {occurrence.course_offering.course.code} {occurrence.session_type} on {occurrence.scheduled_date}')
        self.stdout.write(f'Historical attendance session: {data["historical_session"].id}')
        self.stdout.write(f'Development password for newly created users: {self.password}')
        self.stdout.write(self.style.WARNING('Devices are intentionally not seeded; register them through the normal device flow.'))
