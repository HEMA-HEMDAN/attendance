from pathlib import Path

import pytest
from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.organizations.models import Organization
from apps.accounts.models import Role, User
from apps.courses.models import AcademicYear
from apps.courses.serializers import AcademicYearSerializer
from apps.students.models import Student
from apps.accounts.management.commands.import_attendance_data import Command


@pytest.mark.django_db
def test_explicit_dry_run_does_not_mutate_database(capsys):
    organization = Organization.objects.create(
        name='Import Test University',
        slug='import-test-university',
        timezone='Africa/Cairo',
    )
    source_dir = Path(__file__).resolve().parents[1] / 'seedingFiles'

    with pytest.raises(CommandError, match='Validation failed'):
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
    schedules = command._read_schedule(source_dir / 'scadule.xlsx')
    derived_staff, derived_courses = command._derive_schedule_manifests(schedules)

    assert len(inventory) == 12
    assert len(command.cohort_by_source) == 12
    assert '26140186' not in {row.code for row in rows}
    assert len(rows) == 720
    assert len({row.code for row in rows}) == 719
    assert len(staff) > 0
    assert len(courses) > 0
    assert len(schedules) == 43
    assert len({(row.course_name, row.group_name) for row in schedules if row.group_name}) == 35
    assert len(derived_courses) == 26
    assert all(not row['course_code'] for row in derived_courses)
    assert len(derived_staff) > 0
    assert {row['role'] for row in derived_staff} == {'DOCTOR', 'TEACHING_ASSISTANT'}
    assert all(row['course_code'] == '' for row in derived_courses)
    assert sum(bool(row.cohort) for row in schedules) == 36
    assert sum(not row.cohort for row in schedules) == 7
    assert {row.academic_year for row in enrollments} == {
        '2023-CS', '2023-IS', '2023-IT',
        '2024-CS', '2024-IS', '2024-IT',
        '2025-AI', '2025-CYBERSECURITY', '2025-GENERAL',
        '2026-AI', '2026-CYBERSECURITY', '2026-GENERAL',
    }
    assert command._missing_manifests(source_dir) == {}


def test_academic_year_preview_covers_all_approved_cohorts():
    specs = Command()._academic_year_specs()

    assert {spec['name'] for spec in specs} == set(Command.cohort_by_source.values())
    assert all(spec['organization_required'] for spec in specs)
    assert all(spec['end_date'].year == spec['start_date'].year + 1 for spec in specs)


def test_locations_are_not_a_required_manifest():
    command = Command()
    source_dir = Path(__file__).resolve().parents[1] / 'seedingFiles'

    assert 'locations.csv' not in command._missing_manifests(source_dir)


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


def test_reset_requires_explicit_confirmation():
    with pytest.raises(CommandError, match='confirm-reset'):
        call_command(
            'import_attendance_data',
            '--source-dir', str(Path(__file__).resolve().parents[1] / 'seedingFiles'),
            '--organization', 'unused',
            '--execute',
            '--reset',
        )


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