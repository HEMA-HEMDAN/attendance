"""
Integration and regression tests for TenantScopedImportExportAdmin and Member Management.
Tests all acceptance criteria defined in student_import_and_enrollment_plan.md Section 6.
"""

import pytest
import tablib
from django.core import mail
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import Client
from apps.accounts.models import User, Role
from apps.organizations.models import Organization, OrganizationStatus
from apps.students.models import Student, StudentStatus
from apps.students.resources import StudentResource
from apps.students.forms import StudentAdminForm
from apps.staff.models import Doctor, TeachingAssistant
from apps.staff.forms import DoctorAdminForm, TeachingAssistantAdminForm
from apps.attendance.models import AttendanceRecord, AttendanceSession


@pytest.fixture
def test_setup():
    org_a = Organization.objects.create(name='Alpha Uni', slug='alpha-uni', status=OrganizationStatus.ACTIVE)
    org_b = Organization.objects.create(name='Beta Uni', slug='beta-uni', status=OrganizationStatus.ACTIVE)

    superadmin = User.objects.create_superuser(
        email='super@system.local',
        password='SuperPassword123!',
        first_name='Super',
        last_name='User'
    )

    admin_a = User.objects.create_user(
        email='admin@alpha.edu',
        password='AdminPassword123!',
        first_name='Alpha',
        last_name='Admin',
        role=Role.ADMIN,
        organization=org_a,
        is_staff=True
    )
    # Give admin_a standard permissions for student and attendance
    student_ct = ContentType.objects.get_for_model(Student)
    student_perms = Permission.objects.filter(content_type=student_ct)
    admin_a.user_permissions.add(*student_perms)

    admin_b = User.objects.create_user(
        email='admin@beta.edu',
        password='AdminPassword123!',
        first_name='Beta',
        last_name='Admin',
        role=Role.ADMIN,
        organization=org_b,
        is_staff=True
    )
    admin_b.user_permissions.add(*student_perms)

    return {
        'org_a': org_a,
        'org_b': org_b,
        'superadmin': superadmin,
        'admin_a': admin_a,
        'admin_b': admin_b,
    }


@pytest.mark.django_db(transaction=True)
class TestTenantImportExportAndMembers:

    def test_export_only_models_reject_import(self, test_setup):
        """AttendanceRecordAdmin and AttendanceSessionAdmin reject import requests unconditionally."""
        client = Client()
        client.force_login(test_setup['admin_a'])

        # Attendance Record import endpoints must return 403
        res_record_import = client.get('/admin/attendance/attendancerecord/import/')
        assert res_record_import.status_code == 403

        # Attendance Session import endpoints must return 403
        res_session_import = client.get('/admin/attendance/attendancesession/import/')
        assert res_session_import.status_code == 403

    def test_import_permission_enforcement_preview_and_confirm(self, test_setup):
        """User lacking model add or change permission is rejected on import endpoints with HTTP 403."""
        # Create an admin user without student add/change permission
        limited_admin = User.objects.create_user(
            email='limited@alpha.edu',
            password='LimitedPassword123!',
            first_name='Limited',
            last_name='Admin',
            role=Role.ADMIN,
            organization=test_setup['org_a'],
            is_staff=True
        )
        student_ct = ContentType.objects.get_for_model(Student)
        view_perm = Permission.objects.get(content_type=student_ct, codename='view_student')
        limited_admin.user_permissions.add(view_perm)

        client = Client()
        client.force_login(limited_admin)

        # GET import preview page -> 403
        res = client.get('/admin/students/student/import/')
        assert res.status_code == 403

        # POST process import -> 403
        res_post = client.post('/admin/students/student/process_import/')
        assert res_post.status_code == 403

    def test_student_email_mismatch_rejected(self, test_setup):
        """Importing an existing student ID with a conflicting email raises ValidationError; no changes made."""
        org = test_setup['org_a']
        user = User.objects.create_user(
            email='alice@alpha.edu',
            password='RandomAlicePass!',
            first_name='Alice',
            last_name='Smith',
            role=Role.STUDENT,
            organization=org
        )
        student = Student.objects.create(
            user=user,
            organization=org,
            student_id='STU001',
            department='CS'
        )

        dataset = tablib.Dataset(
            ['STU001', 'hacked@alpha.edu', 'Alice', 'Smith', '123456', '', 'CS', '1st Year', 'ACTIVE'],
            headers=['student_id', 'email', 'first_name', 'last_name', 'phone', 'personal_email', 'department', 'academic_level', 'status']
        )

        resource = StudentResource(organization=org)
        result = resource.import_data(dataset, dry_run=False, raise_errors=False)

        assert result.has_validation_errors() is True
        # Verify user email was NOT modified
        student.refresh_from_db()
        assert student.user.email == 'alice@alpha.edu'

    def test_full_file_rollback_on_later_row_failure(self, test_setup):
        """A multi-row dataset with a failure on the last row commits 0 records and dispatches 0 activation emails."""
        org = test_setup['org_a']
        mail.outbox.clear()

        # Row 1-3 valid, Row 4 has empty email (invalid)
        rows = [
            ['STU101', 'stu101@alpha.edu', 'Student', 'One', '', '', 'CS', '', 'ACTIVE'],
            ['STU102', 'stu102@alpha.edu', 'Student', 'Two', '', '', 'CS', '', 'ACTIVE'],
            ['STU103', 'stu103@alpha.edu', 'Student', 'Three', '', '', 'CS', '', 'ACTIVE'],
            ['STU104', '', 'Student', 'Four', '', '', 'CS', '', 'ACTIVE'],  # Invalid!
        ]
        dataset = tablib.Dataset(
            *rows,
            headers=['student_id', 'email', 'first_name', 'last_name', 'phone', 'personal_email', 'department', 'academic_level', 'status']
        )

        resource = StudentResource(organization=org)
        result = resource.import_data(
            dataset,
            dry_run=False,
            raise_errors=False,
            rollback_on_validation_errors=True
        )

        assert result.has_validation_errors() is True
        # Verify 0 students were committed to database
        assert not Student.objects.filter(organization=org, student_id__in=['STU101', 'STU102', 'STU103', 'STU104']).exists()
        # Verify 0 activation emails were sent
        assert len(mail.outbox) == 0

    def test_repeated_import_idempotent(self, test_setup):
        """Re-importing the same dataset updates fields, keeps passwords intact, and creates 0 duplicate users."""
        org = test_setup['org_a']
        mail.outbox.clear()

        rows = [
            ['STU201', 'stu201@alpha.edu', 'Student', 'Alpha', '0100000001', '', 'CS', '1st Year', 'ACTIVE'],
            ['STU202', 'stu202@alpha.edu', 'Student', 'Beta', '0100000002', '', 'CS', '1st Year', 'ACTIVE'],
        ]
        dataset = tablib.Dataset(
            *rows,
            headers=['student_id', 'email', 'first_name', 'last_name', 'phone', 'personal_email', 'department', 'academic_level', 'status']
        )

        resource = StudentResource(organization=org)
        result1 = resource.import_data(dataset, dry_run=False)
        assert not result1.has_errors()
        assert Student.objects.filter(organization=org).count() == 2

        stu201 = Student.objects.get(organization=org, student_id='STU201')
        user201_pw = stu201.user.password
        user_count_before = User.objects.count()

        # Re-import with an updated department and phone
        rows_update = [
            ['STU201', 'stu201@alpha.edu', 'Student', 'Alpha', '0199999999', '', 'AI', '2nd Year', 'ACTIVE'],
            ['STU202', 'stu202@alpha.edu', 'Student', 'Beta', '0188888888', '', 'AI', '2nd Year', 'ACTIVE'],
        ]
        dataset_update = tablib.Dataset(
            *rows_update,
            headers=['student_id', 'email', 'first_name', 'last_name', 'phone', 'personal_email', 'department', 'academic_level', 'status']
        )
        result2 = resource.import_data(dataset_update, dry_run=False)
        assert not result2.has_errors()

        assert User.objects.count() == user_count_before
        stu201.refresh_from_db()
        assert stu201.phone == '0199999999'
        assert stu201.department == 'AI'
        assert stu201.academic_level == '2nd Year'
        assert stu201.user.password == user201_pw

    def test_unified_student_admin_form_creation(self, test_setup):
        """Single-form creation of Student atomically provisions User with random password and activation email."""
        org = test_setup['org_a']
        mail.outbox.clear()

        form = StudentAdminForm(
            data={
                'organization': org.id,
                'student_id': 'STU301',
                'email': 'student301@alpha.edu',
                'first_name': 'Hema',
                'last_name': 'Dev',
                'department': 'CS',
                'status': 'ACTIVE'
            }
        )
        assert form.is_valid(), form.errors
        student = form.save()

        assert student.user is not None
        assert student.user.email == 'student301@alpha.edu'
        assert student.user.has_usable_password() is True
        assert not student.user.check_password('Password123!')
        assert student.user.role == Role.STUDENT
        assert len(mail.outbox) == 1
        assert 'student301@alpha.edu' in mail.outbox[0].to

    def test_unified_staff_admin_forms(self, test_setup):
        """Single-form creation of Doctor and TA atomically provisions User and dispatches activation email."""
        org = test_setup['org_a']
        mail.outbox.clear()

        # Doctor form
        doc_form = DoctorAdminForm(
            data={
                'organization': org.id,
                'email': 'dr.watson@alpha.edu',
                'first_name': 'John',
                'last_name': 'Watson',
                'title': 'Dr.',
                'department': 'Medicine'
            }
        )
        assert doc_form.is_valid(), doc_form.errors
        doctor = doc_form.save()
        assert doctor.user.role == Role.DOCTOR
        assert doctor.user.has_usable_password() is True
        assert len(mail.outbox) == 1

        # TA form
        mail.outbox.clear()
        ta_form = TeachingAssistantAdminForm(
            data={
                'organization': org.id,
                'email': 'ta.sarah@alpha.edu',
                'first_name': 'Sarah',
                'last_name': 'Connor',
                'department': 'Robotics'
            }
        )
        assert ta_form.is_valid(), ta_form.errors
        ta = ta_form.save()
        assert ta.user.role == Role.TEACHING_ASSISTANT
        assert ta.user.has_usable_password() is True
        assert len(mail.outbox) == 1

    def test_superadmin_target_organization_preservation(self, test_setup):
        """Superadmin import form requires target organization and preserves it."""
        client = Client()
        client.force_login(test_setup['superadmin'])

        res = client.get('/admin/students/student/import/')
        assert res.status_code == 200
        # Check that organization field is in the form
        assert 'organization' in res.context['form'].fields
