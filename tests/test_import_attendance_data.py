from pathlib import Path

import pytest
from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.organizations.models import Organization
from apps.accounts.models import Role, User
from apps.courses.models import AcademicYear, Course, CourseOffering, Schedule
from apps.courses.serializers import AcademicYearSerializer
from apps.groups.models import Group
from apps.locations.models import AttendanceLocation
from apps.students.models import Student, StudentEnrollment
from apps.accounts.management.commands.import_attendance_data import Command


@pytest.mark.django_db
def test_explicit_dry_run_does_not_mutate_database(capsys):
    organization = Organization.objects.create(
        name='Import Test University',
        slug='import-test-university',
        timezone='Africa/Cairo',
    )
    source_dir = Path(__file__).resolve().parents[1] / 'seedingFiles'

    call_command(
        'import_attendance_data',
        '--source-dir', str(source_dir),
        '--organization', organization.slug,
        '--dry-run',
    )

    assert Student.objects.count() == 0
    assert Organization.objects.filter(pk=organization.pk).exists()
    assert 'no database writes performed' in capsys.readouterr().out.lower()


def test_execute_and_dry_run_are_mutually_exclusive():
    with pytest.raises(CommandError, match='cannot be used together'):
        call_command(
            'import_attendance_data',
            '--source-dir', str(Path(__file__).resolve().parents[1] / 'seedingFiles'),
            '--organization', 'unused',
            '--execute',
            '--dry-run',
        )


def test_source_extraction_excludes_conflicting_student_and_keeps_year_files():
    command = Command()
    source_dir = Path(__file__).resolve().parents[1] / 'seedingFiles'
    rows, inventory = command._read_students(source_dir)
    staff, courses, enrollments = command._read_manifests(source_dir)
    schedules = command._read_schedule(source_dir)
    derived_staff, derived_courses = command._derive_schedule_manifests(schedules)

    assert len(inventory) == 12
    assert len(command.cohort_by_source) == 24
    assert '26140186' not in {row.code for row in rows}
    assert len(rows) == 720
    assert len({row.code for row in rows}) == 719
    duplicate_26140279 = [row for row in rows if row.code == '26140279']
    assert len(duplicate_26140279) == 2
    assert len({row.name for row in duplicate_26140279}) == 1
    assert next(row for row in Command._unique_student_rows(rows) if row.code == '26140279') == duplicate_26140279[0]
    assert len(schedules) > 0
    assert len(derived_courses) > 0
    assert len(derived_staff) > 0
    assert {row['role'] for row in derived_staff} == {'DOCTOR', 'TEACHING_ASSISTANT'}
    assert command._validate_manifests(derived_staff, derived_courses, enrollments, rows, schedules) == []


def test_embedded_schedule_preserves_canonical_courses_programs_and_sections():
    command = Command()
    source_dir = Path(__file__).resolve().parents[1] / 'seedingFiles'
    schedules = command._read_schedule(source_dir)
    staff, _ = command._derive_schedule_manifests(schedules)
    staff_names = {row['full_name'] for row in staff}

    assert 'Study Room' not in staff_names
    assert 'Room 1' not in staff_names
    assert 'Ahmed Samir' in staff_names
    assert 'Dr Ahmed Samir' not in staff_names
    assert command._canonical_course_name('Information retrival') == 'Information Retrieval'
    assert command._canonical_course_name('Probability and Statisctics') == 'Probability and Statistics'
    assert command._canonical_course_name('Databases') != command._canonical_course_name('Database Systems')
    assert command._canonical_course_name('Software Engineering') != command._canonical_course_name('Introduction to Software Engineering')
    ai_cyber = [row for row in schedules if row.page == 9]
    assert {row.cohort for row in ai_cyber} == {'2026-AI', '2026-CYBERSECURITY'}
    section = next(row for row in schedules if row.course_name == 'Introduction To Computer Science' and row.group_name == 'Section 1')
    assert section.cohort == '2026-GENERAL'
    assert section.staff_name == 'Abdallah El-Araby'


def test_academic_year_preview_covers_all_approved_cohorts():
    specs = Command()._academic_year_specs()

    assert {spec['name'] for spec in specs} == {'2023-2024', '2024-2025', '2025-2026', '2026-2027'}
    assert all(spec['organization_required'] for spec in specs)
    assert all(spec['end_date'].year == spec['start_date'].year + 1 for spec in specs)


def test_locations_are_not_a_required_manifest():
    command = Command()
    source_dir = Path(__file__).resolve().parents[1] / 'seedingFiles'

    assert 'locations.csv' not in command._missing_manifests(source_dir)


def test_timetable_schedule_provides_valid_schedule_times():
    source_dir = Path(__file__).resolve().parents[1] / 'seedingFiles'
    schedules = Command()._read_schedule(source_dir)

    assert schedules
    assert all(row.day and row.start_time and row.end_time for row in schedules)


@pytest.mark.django_db
def test_cohort_key_is_compatible_with_existing_academic_year_api():
    organization = Organization.objects.create(
        name='Cohort Test University',
        slug='cohort-test-university',
        timezone='Africa/Cairo',
    )
    academic_year = AcademicYear(
        organization=organization,
        name='2024-CS',
        start_date='2024-08-01',
        end_date='2025-07-31',
    )

    academic_year.full_clean()
    academic_year.save()

    assert AcademicYear.objects.filter(organization=organization, name='2024-CS').exists()
    assert AcademicYearSerializer(academic_year).data['name'] == '2024-CS'


def test_no_new_program_business_model_exists():
    model_names = {model.__name__ for model in apps.get_models()}

    assert not model_names.intersection({'AcademicProgram', 'Department', 'Major', 'Track', 'Program', 'Specialization'})


@pytest.mark.django_db
def test_missing_fci_organization_is_auto_created_for_empty_database_import():
    source_dir = Path(__file__).resolve().parents[1] / 'seedingFiles'
    Organization.objects.filter(slug='fci').delete()

    call_command(
        'import_attendance_data',
        '--source-dir', str(source_dir),
        '--organization', 'fci',
        '--execute',
    )

    organization = Organization.objects.get(slug='fci')
    assert organization.name == 'FCI'
    assert organization.slug == 'fci'
    assert Student.objects.filter(organization=organization).count() == 719
    assert User.objects.filter(organization=organization).count() > 0


def test_reset_requires_explicit_confirmation():
    with pytest.raises(CommandError, match='confirm-reset'):
        call_command(
            'import_attendance_data',
            '--source-dir', str(Path(__file__).resolve().parents[1] / 'seedingFiles'),
            '--organization', 'unused',
            '--execute',
            '--reset',
        )


def test_student_password_suffix_is_stable_and_override_is_supported():
    first_default = Command()._student_password_suffix()
    second_default = Command()._student_password_suffix()

    assert first_default == second_default
    assert first_default
    assert Command()._student_password_suffix('explicit-suffix') == 'explicit-suffix'


def test_student_rows_keep_section_metadata_for_enrollment_mapping():
    rows, _ = Command()._read_students(Path(__file__).resolve().parents[1] / 'seedingFiles')

    first_general = next(row for row in rows if row.code == '26140147')
    first_cs = next(row for row in rows if row.code == '24140006')

    assert first_general.section == 'Section 1'
    assert first_cs.section == 'Section 1'


@pytest.mark.django_db
def test_fresh_database_import_creates_required_enrollments_and_is_idempotent():
    source_dir = Path(__file__).resolve().parents[1] / 'seedingFiles'
    organization = Organization.objects.create(
        name='Fresh Import University',
        slug='fresh-import-university',
        timezone='Africa/Cairo',
    )

    call_command(
        'import_attendance_data',
        '--source-dir', str(source_dir),
        '--organization', organization.slug,
        '--execute',
    )

    assert Organization.objects.filter(pk=organization.pk).exists()
    assert User.objects.filter(organization=organization).count() > 0
    assert Student.objects.filter(organization=organization).count() == 719
    assert Student.objects.filter(organization=organization, student_id='26140279').count() == 1
    assert Student.objects.filter(organization=organization, student_id='26140186').count() == 0
    assert StudentEnrollment.objects.filter(student__organization=organization).count() > 0
    assert Group.objects.filter(course_offering__course__organization=organization).count() > 0
    assert AttendanceLocation.objects.filter(organization=organization).count() == 0

    before = {
        'students': Student.objects.filter(organization=organization).count(),
        'users': User.objects.filter(organization=organization).count(),
        'courses': 0,
        'course_offerings': 0,
        'groups': 0,
        'student_enrollments': StudentEnrollment.objects.filter(student__organization=organization).count(),
        'schedules': 0,
    }
    before['courses'] = Course.objects.filter(organization=organization).count()
    before['course_offerings'] = CourseOffering.objects.filter(course__organization=organization).count()
    before['groups'] = Group.objects.filter(course_offering__course__organization=organization).count()
    before['schedules'] = Schedule.objects.filter(course_offering__course__organization=organization).count()

    call_command(
        'import_attendance_data',
        '--source-dir', str(source_dir),
        '--organization', organization.slug,
        '--execute',
    )

    assert Student.objects.filter(organization=organization).count() == before['students']
    assert User.objects.filter(organization=organization).count() == before['users']
    assert Course.objects.filter(organization=organization).count() == before['courses']
    assert CourseOffering.objects.filter(course__organization=organization).count() == before['course_offerings']
    assert Group.objects.filter(course_offering__course__organization=organization).count() == before['groups']
    assert StudentEnrollment.objects.filter(student__organization=organization).count() == before['student_enrollments']
    assert Schedule.objects.filter(course_offering__course__organization=organization).count() == before['schedules']


@pytest.mark.django_db
def test_reset_preserves_admin_roles():
    organization = Organization.objects.create(
        name='Reset Test University',
        slug='reset-test-university',
        timezone='Africa/Cairo',
    )
    admin = User.objects.create_user(
        email='admin@reset.test', password='Pass123!', first_name='Admin', last_name='Test',
        role=Role.ADMIN, organization=organization,
    )
    superadmin = User.objects.create_user(
        email='super@reset.test', password='Pass123!', first_name='Super', last_name='Test',
        role=Role.SUPERADMIN, organization=None,
    )
    User.objects.create_user(
        email='student@reset.test', password='Pass123!', first_name='Student', last_name='Test',
        role=Role.STUDENT, organization=organization,
    )

    Command()._reset_application_data()

    assert User.objects.filter(pk=admin.pk).exists()
    assert User.objects.filter(pk=superadmin.pk).exists()
    assert not User.objects.filter(email='student@reset.test').exists()