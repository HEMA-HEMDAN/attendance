from datetime import time
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.accounts.management.commands.import_attendance_data import Command, ScheduleSourceRow
from apps.accounts.models import Role, User
from apps.courses.models import Course, CourseOffering, Schedule
from apps.groups.models import Group
from apps.organizations.models import Organization
from apps.staff.models import Doctor, TeachingAssistant
from apps.students.models import Student, StudentEnrollment


SERVER_DIR = Path(__file__).resolve().parents[1]
SOURCE_DIR = SERVER_DIR / 'seedingFiles'


def test_timetable_and_rosters_parse_from_supplied_csvs():
    command = Command()
    errors = []
    cohort_map = command._read_cohort_map(SOURCE_DIR / 'cohort_map.csv', errors)
    students, row_count, conflicts = command._read_students(
        SOURCE_DIR / 'studentCsv', cohort_map, {'26140186'}, errors
    )
    schedules = command._read_schedule(
        SOURCE_DIR / 'timetable_damanhour_fci_2026_2027_T1.csv', cohort_map, errors
    )

    assert not errors
    assert len(cohort_map) == 12
    assert row_count == 722
    assert len(students) == 719
    assert conflicts == ['26140186']
    shared_student = next(student for student in students if student.code == '26140279')
    assert shared_student.affiliations == {('L1-AI', '1'), ('L1-GENERAL', '5')}
    assert len(schedules) == 156
    assert {row.day for row in schedules} == {0, 1, 2, 3, 5, 6}
    assert all(row.start_time < row.end_time for row in schedules)


def test_conflicting_student_code_is_reported_until_explicitly_excluded():
    command = Command()
    errors = []
    cohort_map = command._read_cohort_map(SOURCE_DIR / 'cohort_map.csv', errors)
    _students, _row_count, conflicts = command._read_students(
        SOURCE_DIR / 'studentCsv', cohort_map, set(), errors
    )

    assert conflicts == ['26140186']
    assert any('Conflicting names for student 26140186' in error for error in errors)


def test_course_is_shared_for_matching_slots_and_split_for_different_slots():
    rows = [
        ScheduleSourceRow(
            'Doctor One', Role.DOCTOR, 5, time(9), time(11), 'English',
            'LECTURE', ('L1-GENERAL',), (), 'Hall 1', 2,
        ),
        ScheduleSourceRow(
            'Doctor One', Role.DOCTOR, 5, time(9), time(11), 'English',
            'LECTURE', ('L1-AI',), (), 'Hall 2', 3,
        ),
        ScheduleSourceRow(
            'Doctor Two', Role.DOCTOR, 5, time(11), time(13), 'English',
            'LECTURE', ('L1-CYBERSECURITY',), (), 'Hall 3', 4,
        ),
    ]
    cohort_map = {
        ('1', 'GENERAL'): {'cohort_key': 'L1-GENERAL', 'label': 'Level 1 General'},
        ('1', 'AI'): {'cohort_key': 'L1-AI', 'label': 'Level 1 AI'},
        ('1', 'CYBERSECURITY'): {
            'cohort_key': 'L1-CYBERSECURITY', 'label': 'Level 1 Cybersecurity',
        },
    }
    errors = []
    plan = Command()._build_plan([], rows, cohort_map, errors)

    assert not errors
    assert len(plan['variants']) == 2
    names = {item['display_name'] for item in plan['variants'].values()}
    assert 'English (Level 1 AI / Level 1 General)' in names
    assert 'English (Level 1 Cybersecurity)' in names


def test_staff_title_parser_and_cairo_server_timezone():
    assert Command._parse_staff('أ.د. عمرو أبو هاني') == ('عمرو أبو هاني', Role.DOCTOR)
    assert Command._parse_staff('م. دنيا ياسر') == ('دنيا ياسر', Role.TEACHING_ASSISTANT)
    assert settings.TIME_ZONE == 'Africa/Cairo'


@pytest.mark.django_db
def test_dry_run_does_not_write_database(capsys):
    before = User.objects.count(), Organization.objects.count()

    call_command(
        'import_attendance_data',
        '--source-dir', str(SOURCE_DIR),
        '--dry-run',
        '--exclude-student-code', '26140186',
    )

    assert (User.objects.count(), Organization.objects.count()) == before
    assert 'no database writes performed' in capsys.readouterr().out.lower()


def test_execute_and_dry_run_are_mutually_exclusive():
    with pytest.raises(CommandError, match='not allowed with argument|cannot be used together'):
        call_command(
            'import_attendance_data',
            '--source-dir', str(SOURCE_DIR),
            '--execute',
            '--dry-run',
        )


@pytest.mark.django_db
@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
def test_execute_creates_accounts_enrollments_and_is_idempotent():
    options = [
        '--source-dir', str(SOURCE_DIR),
        '--organization', 'fci-test',
        '--execute',
        '--academic-year-start', '2026-08-01',
        '--academic-year-end', '2027-07-31',
        '--exclude-student-code', '26140186',
    ]
    call_command('import_attendance_data', *options)

    organization = Organization.objects.get(slug='fci-test')
    assert organization.timezone == 'Africa/Cairo'
    assert Student.objects.filter(organization=organization).count() == 719
    assert Doctor.objects.filter(organization=organization).count() > 0
    assert TeachingAssistant.objects.filter(organization=organization).count() > 0
    assert Course.objects.filter(organization=organization).count() == 62
    assert CourseOffering.objects.filter(course__organization=organization).count() == 62
    assert Group.objects.filter(course_offering__course__organization=organization).count() == 128
    assert Schedule.objects.filter(course_offering__course__organization=organization).count() == 190
    assert StudentEnrollment.objects.filter(student__organization=organization).count() == 4980
    assert Schedule.objects.filter(
        course_offering__course__organization=organization,
        room_label__gt='',
    ).exists()

    student = Student.objects.get(organization=organization, student_id='26140279')
    assert student.user.email == '26140279@fci.edu'
    assert student.user.check_password('26140279#Fci!')
    staff_user = User.objects.filter(
        organization=organization,
        role__in=[Role.DOCTOR, Role.TEACHING_ASSISTANT],
    ).first()
    assert staff_user.check_password(staff_user.email)

    before = (
        User.objects.filter(organization=organization).count(),
        Student.objects.filter(organization=organization).count(),
        Course.objects.filter(organization=organization).count(),
        CourseOffering.objects.filter(course__organization=organization).count(),
        Group.objects.filter(course_offering__course__organization=organization).count(),
        Schedule.objects.filter(course_offering__course__organization=organization).count(),
        StudentEnrollment.objects.filter(student__organization=organization).count(),
    )
    call_command('import_attendance_data', *options)
    after = (
        User.objects.filter(organization=organization).count(),
        Student.objects.filter(organization=organization).count(),
        Course.objects.filter(organization=organization).count(),
        CourseOffering.objects.filter(course__organization=organization).count(),
        Group.objects.filter(course_offering__course__organization=organization).count(),
        Schedule.objects.filter(course_offering__course__organization=organization).count(),
        StudentEnrollment.objects.filter(student__organization=organization).count(),
    )
    assert after == before