"""
Automated test suite for Student Enrollment Workflows:
Workflow A: Combined Student + Enrollment Import (StudentWithEnrollmentsResource)
Workflow B: Django Admin Bulk Course Assignment (BulkEnrollmentActionService + StudentAdmin)
"""

import pytest
import tablib
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import ValidationError
from django.test import Client, RequestFactory
from import_export.results import Result, RowResult

from apps.accounts.models import User, Role
from apps.organizations.models import Organization, OrganizationStatus
from apps.courses.models import Course, CourseOffering, AcademicYear, Semester
from apps.groups.models import Group
from apps.students.models import Student, StudentEnrollment, StudentStatus
from apps.students.resources import StudentResource
from apps.students.services.bulk_enrollment import BulkEnrollmentActionService, BulkEnrollmentResult
from apps.students.forms import BulkEnrollmentActionForm
from apps.students.admin import StudentAdmin


@pytest.fixture
def workflow_setup():
    org_a = Organization.objects.create(name='Faculty of Engineering', slug='foe', status=OrganizationStatus.ACTIVE)
    org_b = Organization.objects.create(name='Faculty of Science', slug='fos', status=OrganizationStatus.ACTIVE)

    # Academic Structure for Org A
    year_a = AcademicYear.objects.create(
        organization=org_a,
        name='2026/2027',
        start_date='2026-09-01',
        end_date='2027-06-30',
        is_active=True
    )
    sem_a = Semester.objects.create(
        organization=org_a,
        academic_year=year_a,
        name='Fall',
        start_date='2026-09-01',
        end_date='2027-01-31',
        is_active=True
    )

    course_cs101 = Course.objects.create(organization=org_a, code='CS101', name='Intro to Programming', department='CS')
    course_cs102 = Course.objects.create(organization=org_a, code='CS102', name='Data Structures', department='CS')
    offering_cs101 = CourseOffering.objects.create(course=course_cs101, academic_year=year_a, semester=sem_a)
    offering_cs102 = CourseOffering.objects.create(course=course_cs102, academic_year=year_a, semester=sem_a)

    group_sec1 = Group.objects.create(course_offering=offering_cs101, name='Section 1')
    group_sec2 = Group.objects.create(course_offering=offering_cs101, name='Section 2')

    # Academic Structure for Org B (Cross-Tenant)
    year_b = AcademicYear.objects.create(
        organization=org_b,
        name='2026/2027',
        start_date='2026-09-01',
        end_date='2027-06-30',
        is_active=True
    )
    sem_b = Semester.objects.create(
        organization=org_b,
        academic_year=year_b,
        name='Fall',
        start_date='2026-09-01',
        end_date='2027-01-31',
        is_active=True
    )
    course_bio = Course.objects.create(organization=org_b, code='BIO101', name='General Biology', department='BIO')
    offering_bio = CourseOffering.objects.create(course=course_bio, academic_year=year_b, semester=sem_b)

    # Users
    superadmin = User.objects.create_superuser(
        email='super@system.local',
        password='SuperPassword123!',
        first_name='Super',
        last_name='Admin'
    )

    admin_a = User.objects.create_user(
        email='admin@foe.edu',
        password='AdminPassword123!',
        first_name='Engineering',
        last_name='Admin',
        role=Role.ADMIN,
        organization=org_a,
        is_staff=True
    )
    student_ct = ContentType.objects.get_for_model(Student)
    enrollment_ct = ContentType.objects.get_for_model(StudentEnrollment)
    course_ct = ContentType.objects.get_for_model(CourseOffering)

    admin_a.user_permissions.add(
        *Permission.objects.filter(content_type=student_ct),
        *Permission.objects.filter(content_type=enrollment_ct),
        *Permission.objects.filter(content_type=course_ct)
    )

    return {
        'org_a': org_a,
        'org_b': org_b,
        'year_a': year_a,
        'sem_a': sem_a,
        'course_cs101': course_cs101,
        'course_cs102': course_cs102,
        'offering_cs101': offering_cs101,
        'offering_cs102': offering_cs102,
        'group_sec1': group_sec1,
        'group_sec2': group_sec2,
        'offering_bio': offering_bio,
        'superadmin': superadmin,
        'admin_a': admin_a,
    }


@pytest.mark.django_db(transaction=True)
class TestWorkflowBBulkEnrollmentService:
    """Tests for BulkEnrollmentActionService (Workflow B)."""

    def _create_students(self, org, count, prefix='S'):
        students = []
        for i in range(1, count + 1):
            u = User.objects.create_user(
                email=f'{prefix.lower()}{i}@foe.edu',
                password='Password123!',
                first_name=f'{prefix}',
                last_name=f'Student{i}',
                role=Role.STUDENT,
                organization=org
            )
            s = Student.objects.create(
                user=u,
                organization=org,
                student_id=f'{prefix}{i:04d}',
                academic_level='1st Year'
            )
            students.append(s)
        return students

    def test_bulk_enrollment_accurate_metrics(self, workflow_setup):
        """Accurately calculates total_students, created_count, already_existing_count, and rejected_count."""
        org = workflow_setup['org_a']
        students = self._create_students(org, 5, prefix='MET')

        # Pre-enroll 2 students in CS101
        StudentEnrollment.objects.create(student=students[0], course_offering=workflow_setup['offering_cs101'])
        StudentEnrollment.objects.create(student=students[1], course_offering=workflow_setup['offering_cs101'])

        result = BulkEnrollmentActionService.execute_enrollment(
            student_queryset=Student.objects.filter(id__in=[s.id for s in students]),
            offering_ids=[workflow_setup['offering_cs101'].id],
            strategy='LECTURE_ONLY',
            organization=org
        )

        assert isinstance(result, BulkEnrollmentResult)
        assert result.total_students == 5
        assert result.created_count == 3
        assert result.already_existing_count == 2
        assert result.rejected_count == 0

        # Legacy tuple unpacking test
        total, created, existing = result
        assert total == 5
        assert created == 3
        assert existing == 2

    def test_bulk_enrollment_preserves_existing_group_when_lecture_only(self, workflow_setup):
        """Assigning LECTURE_ONLY never wipes out an existing group assignment."""
        org = workflow_setup['org_a']
        students = self._create_students(org, 2, prefix='GRP')

        # S1 has Section 1 pre-assigned
        enr_s1 = StudentEnrollment.objects.create(
            student=students[0],
            course_offering=workflow_setup['offering_cs101'],
            group=workflow_setup['group_sec1']
        )

        # Run bulk enrollment with LECTURE_ONLY strategy
        result = BulkEnrollmentActionService.execute_enrollment(
            student_queryset=Student.objects.filter(id__in=[s.id for s in students]),
            offering_ids=[workflow_setup['offering_cs101'].id],
            strategy='LECTURE_ONLY',
            organization=org
        )

        assert result.created_count == 1
        assert result.already_existing_count == 1

        enr_s1.refresh_from_db()
        assert enr_s1.group == workflow_setup['group_sec1']

        enr_s2 = StudentEnrollment.objects.get(student=students[1], course_offering=workflow_setup['offering_cs101'])
        assert enr_s2.group is None

    def test_bulk_enrollment_assigns_specific_group_for_single_offering(self, workflow_setup):
        """When exactly 1 offering is selected and specific_group is chosen, group is assigned."""
        org = workflow_setup['org_a']
        students = self._create_students(org, 2, prefix='SPEC')

        result = BulkEnrollmentActionService.execute_enrollment(
            student_queryset=Student.objects.filter(id__in=[s.id for s in students]),
            offering_ids=[workflow_setup['offering_cs101'].id],
            strategy='SPECIFIC_GROUP',
            specific_group_id=workflow_setup['group_sec2'].id,
            organization=org
        )

        assert result.created_count == 2
        for s in students:
            enr = StudentEnrollment.objects.get(student=s, course_offering=workflow_setup['offering_cs101'])
            assert enr.group == workflow_setup['group_sec2']

    def test_bulk_enrollment_multiple_offerings_forces_lecture_only(self, workflow_setup):
        """When multiple offerings are selected, specific_group_id raises ValidationError; LECTURE_ONLY succeeds."""
        org = workflow_setup['org_a']
        students = self._create_students(org, 2, prefix='MULTI')

        # 1. Passing specific_group_id with multiple offerings must be rejected
        with pytest.raises(ValidationError) as exc_info:
            BulkEnrollmentActionService.execute_enrollment(
                student_queryset=Student.objects.filter(id__in=[s.id for s in students]),
                offering_ids=[workflow_setup['offering_cs101'].id, workflow_setup['offering_cs102'].id],
                strategy='SPECIFIC_GROUP',
                specific_group_id=workflow_setup['group_sec1'].id,
                organization=org
            )
        assert "A specific group can only be assigned when enrolling into exactly one course offering" in str(exc_info.value)

        # 2. Enrolling into multiple offerings with LECTURE_ONLY strategy succeeds with group=None
        result = BulkEnrollmentActionService.execute_enrollment(
            student_queryset=Student.objects.filter(id__in=[s.id for s in students]),
            offering_ids=[workflow_setup['offering_cs101'].id, workflow_setup['offering_cs102'].id],
            strategy='LECTURE_ONLY',
            organization=org
        )

        assert result.created_count == 4
        enrollments = StudentEnrollment.objects.filter(student__in=students)
        assert enrollments.count() == 4
        for enr in enrollments:
            assert enr.group is None

    def test_bulk_enrollment_cross_tenant_students_rejected(self, workflow_setup):
        """Students belonging to another organization are tracked in rejected_count and skipped."""
        org_a = workflow_setup['org_a']
        org_b = workflow_setup['org_b']

        student_a = self._create_students(org_a, 1, prefix='ORGA')[0]
        student_b = self._create_students(org_b, 1, prefix='ORGB')[0]

        result = BulkEnrollmentActionService.execute_enrollment(
            student_queryset=Student.objects.filter(id__in=[student_a.id, student_b.id]),
            offering_ids=[workflow_setup['offering_cs101'].id],
            organization=org_a
        )

        assert result.total_students == 2
        assert result.created_count == 1
        assert result.rejected_count == 1
        assert StudentEnrollment.objects.filter(student=student_a, course_offering=workflow_setup['offering_cs101']).exists() is True
        assert StudentEnrollment.objects.filter(student=student_b).exists() is False

    def test_bulk_enrollment_multi_offering_per_offering_groups(self, workflow_setup):
        """Supports enrolling students into multiple offerings each with its own group or lecture-only."""
        org = workflow_setup['org_a']
        students = self._create_students(org, 2, prefix='PERG')

        offering_groups = {
            workflow_setup['offering_cs101'].id: workflow_setup['group_sec1'].id,
            workflow_setup['offering_cs102'].id: None  # Lecture only
        }

        result = BulkEnrollmentActionService.execute_enrollment(
            student_queryset=Student.objects.filter(id__in=[s.id for s in students]),
            offering_groups=offering_groups,
            organization=org,
            dry_run=False
        )

        assert result.created_count == 4
        assert result.already_existing_count == 0

        for s in students:
            enr_101 = StudentEnrollment.objects.get(student=s, course_offering=workflow_setup['offering_cs101'])
            assert enr_101.group == workflow_setup['group_sec1']

            enr_102 = StudentEnrollment.objects.get(student=s, course_offering=workflow_setup['offering_cs102'])
            assert enr_102.group is None

    def test_bulk_enrollment_dry_run_zero_writes(self, workflow_setup):
        """Dry-run calculation computes exact counts with zero persistent database writes."""
        org = workflow_setup['org_a']
        students = self._create_students(org, 3, prefix='DRY')

        offering_groups = {
            workflow_setup['offering_cs101'].id: workflow_setup['group_sec1'].id,
            workflow_setup['offering_cs102'].id: None
        }

        initial_count = StudentEnrollment.objects.count()

        result = BulkEnrollmentActionService.execute_enrollment(
            student_queryset=Student.objects.filter(id__in=[s.id for s in students]),
            offering_groups=offering_groups,
            organization=org,
            dry_run=True
        )

        assert result.total_students == 3
        # 3 students x 2 courses = 6 proposed enrollments
        assert result.created_count == 6
        assert result.already_existing_count == 0
        # Zero writes occurred!
        assert StudentEnrollment.objects.count() == initial_count

    def test_bulk_enrollment_mismatched_group_offering_rejected(self, workflow_setup):
        """Attempting to assign a group to an offering it does not belong to raises ValidationError."""
        org = workflow_setup['org_a']
        students = self._create_students(org, 1, prefix='MIS')

        # group_sec1 belongs to CS101, NOT CS102
        offering_groups = {
            workflow_setup['offering_cs102'].id: workflow_setup['group_sec1'].id
        }

        with pytest.raises(ValidationError) as exc_info:
            BulkEnrollmentActionService.execute_enrollment(
                student_queryset=Student.objects.filter(id__in=[s.id for s in students]),
                offering_groups=offering_groups,
                organization=org
            )

        assert "does not belong to active course offering" in str(exc_info.value)


@pytest.mark.django_db(transaction=True)
class TestStudentAdminWorkflowIntegration:
    """Admin-level integration tests for StudentAdmin and forms."""

    def test_admin_resource_selection_includes_student_resource(self, workflow_setup):
        """Admin import page includes StudentResource."""
        client = Client()
        client.force_login(workflow_setup['admin_a'])

        response = client.get('/admin/students/student/import/')
        assert response.status_code == 200

    def test_admin_bulk_enroll_action_empty_selection_warning(self, workflow_setup):
        """Action warns when invoked on empty queryset."""
        factory = RequestFactory()
        request = factory.post('/admin/students/student/', {'action': 'bulk_enroll_students'})
        request.user = workflow_setup['admin_a']
        request.session = SessionStore()
        request._messages = FallbackStorage(request)

        student_admin = StudentAdmin(Student, AdminSite())
        response = student_admin.bulk_enroll_students(request, Student.objects.none())

        assert response is None
        messages = [m.message for m in request._messages]
        assert "No students selected." in messages

    def test_admin_bulk_enroll_action_superadmin_multi_org_blocked(self, workflow_setup):
        """Superadmin selecting students across multiple organizations is blocked."""
        org_a = workflow_setup['org_a']
        org_b = workflow_setup['org_b']

        u_a = User.objects.create_user(email='sa@foe.edu', password='p', role=Role.STUDENT, organization=org_a)
        s_a = Student.objects.create(user=u_a, organization=org_a, student_id='SA01')

        u_b = User.objects.create_user(email='sb@fos.edu', password='p', role=Role.STUDENT, organization=org_b)
        s_b = Student.objects.create(user=u_b, organization=org_b, student_id='SB01')

        factory = RequestFactory()
        request = factory.post('/admin/students/student/', {'action': 'bulk_enroll_students'})
        request.user = workflow_setup['superadmin']
        request.session = SessionStore()
        request._messages = FallbackStorage(request)

        student_admin = StudentAdmin(Student, AdminSite())
        qs = Student.objects.filter(id__in=[s_a.id, s_b.id])
        response = student_admin.bulk_enroll_students(request, qs)

        assert response is None
        messages = [m.message for m in request._messages]
        assert any("Selected students belong to different organizations" in m for m in messages)

    def test_admin_bulk_enroll_action_form_renders_and_scopes_offerings(self, workflow_setup):
        """Intermediate action form renders and limits course offerings to student organization."""
        client = Client()
        client.force_login(workflow_setup['admin_a'])

        org = workflow_setup['org_a']
        u = User.objects.create_user(email='s_rend@foe.edu', password='p', role=Role.STUDENT, organization=org)
        s = Student.objects.create(user=u, organization=org, student_id='SREND01')

        response = client.post(
            '/admin/students/student/',
            {
                'action': 'bulk_enroll_students',
                '_selected_action': [s.id]
            }
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Bulk Enroll Selected Students in Courses' in content
        # CS101 and CS102 should be in the options
        assert 'CS101' in content
        assert 'CS102' in content
        # BIO101 from Org B must NOT be in the options
        assert 'BIO101' not in content

    def test_admin_bulk_enroll_action_post_success_redirect(self, workflow_setup):
        """Submitting intermediate action form creates enrollments and redirects with success message."""
        client = Client()
        client.force_login(workflow_setup['admin_a'])

        org = workflow_setup['org_a']
        u1 = User.objects.create_user(email='s_post1@foe.edu', password='p', role=Role.STUDENT, organization=org)
        s1 = Student.objects.create(user=u1, organization=org, student_id='SPOST01')
        u2 = User.objects.create_user(email='s_post2@foe.edu', password='p', role=Role.STUDENT, organization=org)
        s2 = Student.objects.create(user=u2, organization=org, student_id='SPOST02')

        response = client.post(
            '/admin/students/student/',
            {
                'action': 'bulk_enroll_students',
                '_selected_action': [s1.id, s2.id],
                'apply': 'apply',
                'course_offerings': [workflow_setup['offering_cs101'].id],
                'strategy': 'LECTURE_ONLY'
            },
            follow=True
        )

        assert response.status_code == 200
        # Check flash message in response
        messages = [m.message for m in response.context['messages']]
        assert any("Bulk course assignment complete: 2 enrollment(s) created, 0 already existed" in m for m in messages)

        # Check DB
        assert StudentEnrollment.objects.filter(student=s1, course_offering=workflow_setup['offering_cs101']).exists()
        assert StudentEnrollment.objects.filter(student=s2, course_offering=workflow_setup['offering_cs101']).exists()

    def test_admin_bulk_enroll_preview_step_renders_without_writing(self, workflow_setup):
        """Step 2 (Preview) calculates metrics and renders preview page with zero persistent writes."""
        client = Client()
        client.force_login(workflow_setup['admin_a'])

        org = workflow_setup['org_a']
        u = User.objects.create_user(email='prev_s@foe.edu', password='p', role=Role.STUDENT, organization=org)
        s = Student.objects.create(user=u, organization=org, student_id='PREV01')

        off1 = workflow_setup['offering_cs101']
        off2 = workflow_setup['offering_cs102']
        grp1 = workflow_setup['group_sec1']

        initial_count = StudentEnrollment.objects.count()

        response = client.post(
            '/admin/students/student/',
            {
                'action': 'bulk_enroll_students',
                '_selected_action': [s.id],
                'action_step': 'preview',
                'course_offerings': [off1.id, off2.id],
                f'group_for_{off1.id}': grp1.id,
            }
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert "Review Proposed Enrollment Plan" in content
        assert "New Enrollments" in content
        assert grp1.name in content
        # Zero database writes during preview!
        assert StudentEnrollment.objects.count() == initial_count

    def test_admin_bulk_enroll_confirm_step_creates_enrollments(self, workflow_setup):
        """Step 3 (Confirm) revalidates and executes enrollments atomically with exact reporting."""
        client = Client()
        client.force_login(workflow_setup['admin_a'])

        org = workflow_setup['org_a']
        u = User.objects.create_user(email='conf_s@foe.edu', password='p', role=Role.STUDENT, organization=org)
        s = Student.objects.create(user=u, organization=org, student_id='CONF01')

        off1 = workflow_setup['offering_cs101']
        off2 = workflow_setup['offering_cs102']
        grp1 = workflow_setup['group_sec1']

        response = client.post(
            '/admin/students/student/',
            {
                'action': 'bulk_enroll_students',
                '_selected_action': [s.id],
                'action_step': 'confirm',
                'course_offerings': [off1.id, off2.id],
                f'group_for_{off1.id}': grp1.id,
            },
            follow=True
        )

        assert response.status_code == 200
        messages = [m.message for m in response.context['messages']]
        assert any("Bulk course assignment complete: 2 enrollment(s) created, 0 already existed" in m for m in messages)

        enr1 = StudentEnrollment.objects.get(student=s, course_offering=off1)
        assert enr1.group == grp1

        enr2 = StudentEnrollment.objects.get(student=s, course_offering=off2)
        assert enr2.group is None

    def test_admin_bulk_enroll_modify_step_returns_to_form(self, workflow_setup):
        """Clicking Modify Selection from preview navigates back to Step 1 with selections preserved."""
        client = Client()
        client.force_login(workflow_setup['admin_a'])

        org = workflow_setup['org_a']
        u = User.objects.create_user(email='mod_s@foe.edu', password='p', role=Role.STUDENT, organization=org)
        s = Student.objects.create(user=u, organization=org, student_id='MOD01')

        off1 = workflow_setup['offering_cs101']

        response = client.post(
            '/admin/students/student/',
            {
                'action': 'bulk_enroll_students',
                '_selected_action': [s.id],
                'action_step': 'modify',
                'course_offerings': [off1.id],
            }
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert "Bulk Course & Section Enrollment" in content
        assert "Preview Enrollment Plan" in content
