"""
Automated test suite for Unified People Import & Staff Academic Assignments.

Covers:
1. Independent People Import (Student, Doctor, TA) with zero implicit enrollments.
2. StaffAssignmentService:
   - Doctor assignments, reassignments (replacing previous doctor), and schedule syncing.
   - TA assignments, reassignments (replacing previous TA), and schedule syncing.
   - Genuine dry-run previews with 0 database writes.
   - Tenant isolation and cross-org validation.
3. Streamlined Inline Schedule Forms:
   - DoctorScheduleInlineForm (Lectures only, auto-sets session_type=LECTURE, group=None).
   - TAScheduleInlineForm (Labs only, auto-sets session_type=LAB, validates group belongs to offering).
4. Staff Admin Inlines & Direct Shortcut URLs (Option 1 & Option 2):
   - Inlines prevent inline creation (has_add_permission=False, extra=0).
   - Detail change forms display direct action shortcut buttons.
   - Single-object views: /admin/staff/doctor/<id>/assign-courses/ and /admin/staff/teachingassistant/<id>/assign-groups/.
5. Django Admin Multi-Step Workflow:
   - DoctorAdmin assign_courses_to_doctor (Form -> Dry-Run Preview -> Confirm).
   - TeachingAssistantAdmin assign_groups_to_ta with Course-Driven Allocation (Form -> Dry-Run Preview -> Confirm).
"""

import pytest
import tablib
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.accounts.models import User, Role
from apps.organizations.models import Organization, OrganizationStatus
from apps.courses.models import Course, CourseOffering, CourseOfferingStatus, AcademicYear, Semester, Schedule, SessionType
from apps.groups.models import Group, GroupStatus
from apps.staff.models import Doctor, TeachingAssistant
from apps.students.models import Student, StudentEnrollment
from apps.staff.resources import DoctorResource, TeachingAssistantResource
from apps.students.resources import StudentResource
from apps.staff.services.staff_assignment import StaffAssignmentService, StaffAssignmentResult
from apps.staff.admin import DoctorAdmin, TeachingAssistantAdmin, CourseOfferingInline, AssignedGroupInline, DoctorScheduleInline, TAScheduleInline
from apps.staff.forms import DoctorScheduleInlineForm, TAScheduleInlineForm


@pytest.fixture
def academic_setup():
    org_a = Organization.objects.create(name='Faculty of Engineering', slug='foe', status=OrganizationStatus.ACTIVE)
    org_b = Organization.objects.create(name='Faculty of Science', slug='fos', status=OrganizationStatus.ACTIVE)

    # Admin user for Org A
    admin_u = User.objects.create_user(
        email='admin_foe@foe.edu', password='Password123!', role=Role.ADMIN,
        organization=org_a, is_staff=True, is_superuser=False
    )

    # Assign permissions to admin_u for admin interface testing
    for model in [Doctor, TeachingAssistant, CourseOffering, Group, Student, StudentEnrollment, Schedule]:
        ct = ContentType.objects.get_for_model(model)
        admin_u.user_permissions.add(*Permission.objects.filter(content_type=ct))

    # Academic Year & Semester for Org A
    year_a = AcademicYear.objects.create(
        organization=org_a, name='2026/2027', start_date='2026-09-01', end_date='2027-06-30', is_active=True
    )
    sem_a = Semester.objects.create(
        organization=org_a, academic_year=year_a, name='Fall', start_date='2026-09-01', end_date='2027-01-31', is_active=True
    )

    # Academic Year & Semester for Org B
    year_b = AcademicYear.objects.create(
        organization=org_b, name='2026/2027', start_date='2026-09-01', end_date='2027-06-30', is_active=True
    )
    sem_b = Semester.objects.create(
        organization=org_b, academic_year=year_b, name='Fall', start_date='2026-09-01', end_date='2027-01-31', is_active=True
    )

    # Courses & Offerings for Org A
    c1 = Course.objects.create(organization=org_a, code='CS101', name='Intro to CS')
    c2 = Course.objects.create(organization=org_a, code='CS102', name='Data Structures')
    c3 = Course.objects.create(organization=org_a, code='CS103', name='Algorithms')

    off1 = CourseOffering.objects.create(course=c1, academic_year=year_a, semester=sem_a, status=CourseOfferingStatus.ACTIVE)
    off2 = CourseOffering.objects.create(course=c2, academic_year=year_a, semester=sem_a, status=CourseOfferingStatus.ACTIVE)
    off3 = CourseOffering.objects.create(course=c3, academic_year=year_a, semester=sem_a, status=CourseOfferingStatus.ACTIVE)

    # Course for Org B
    c_b = Course.objects.create(organization=org_b, code='BIO101', name='Biology')
    off_b = CourseOffering.objects.create(course=c_b, academic_year=year_b, semester=sem_b, status=CourseOfferingStatus.ACTIVE)

    # Groups for Org A
    g1 = Group.objects.create(course_offering=off1, name='Section 1', status=GroupStatus.ACTIVE)
    g2 = Group.objects.create(course_offering=off1, name='Section 2', status=GroupStatus.ACTIVE)
    g3 = Group.objects.create(course_offering=off2, name='Section A', status=GroupStatus.ACTIVE)

    # Group for Org B
    g_b = Group.objects.create(course_offering=off_b, name='Bio Section 1', status=GroupStatus.ACTIVE)

    # Doctors for Org A
    u_doc1 = User.objects.create_user(email='doc1@foe.edu', password='Password123!', first_name='Ahmed', last_name='Zewail', role=Role.DOCTOR, organization=org_a)
    doc1 = Doctor.objects.create(user=u_doc1, organization=org_a, title='Prof.', department='CS')

    u_doc2 = User.objects.create_user(email='doc2@foe.edu', password='Password123!', first_name='Magdi', last_name='Yacoub', role=Role.DOCTOR, organization=org_a)
    doc2 = Doctor.objects.create(user=u_doc2, organization=org_a, title='Dr.', department='CS')

    # Doctor for Org B
    u_doc_b = User.objects.create_user(email='doc_b@fos.edu', password='Password123!', first_name='Farouk', last_name='El-Baz', role=Role.DOCTOR, organization=org_b)
    doc_b = Doctor.objects.create(user=u_doc_b, organization=org_b, title='Prof.', department='Bio')

    # Teaching Assistants for Org A
    u_ta1 = User.objects.create_user(email='ta1@foe.edu', password='Password123!', first_name='Kareem', last_name='Adel', role=Role.TEACHING_ASSISTANT, organization=org_a)
    ta1 = TeachingAssistant.objects.create(user=u_ta1, organization=org_a, department='CS')

    u_ta2 = User.objects.create_user(email='ta2@foe.edu', password='Password123!', first_name='Salma', last_name='Tarek', role=Role.TEACHING_ASSISTANT, organization=org_a)
    ta2 = TeachingAssistant.objects.create(user=u_ta2, organization=org_a, department='CS')

    # TA for Org B
    u_ta_b = User.objects.create_user(email='ta_b@fos.edu', password='Password123!', first_name='Mona', last_name='Ibrahim', role=Role.TEACHING_ASSISTANT, organization=org_b)
    ta_b = TeachingAssistant.objects.create(user=u_ta_b, organization=org_b, department='Bio')

    return {
        'org_a': org_a,
        'org_b': org_b,
        'admin_a': admin_u,
        'year_a': year_a,
        'sem_a': sem_a,
        'offering_cs101': off1,
        'offering_cs102': off2,
        'offering_cs103': off3,
        'offering_bio101': off_b,
        'group_sec1': g1,
        'group_sec2': g2,
        'group_secA': g3,
        'group_bio_sec1': g_b,
        'doc1': doc1,
        'doc2': doc2,
        'doc_b': doc_b,
        'ta1': ta1,
        'ta2': ta2,
        'ta_b': ta_b,
    }


# ==============================================================================
# 1. Independent People Import Tests
# ==============================================================================

@pytest.mark.django_db(transaction=True)
class TestIndependentPeopleImport:
    """Verifies that Student, Doctor, and TA imports provision accounts independently of enrollments."""

    def test_student_import_creates_profile_without_enrollments(self, academic_setup):
        """Student import creates user and student profile, but zero course enrollments."""
        org = academic_setup['org_a']
        resource = StudentResource()
        resource.organization = org

        dataset = tablib.Dataset(
            ['STU901', 'stu901@foe.edu', 'Layla', 'Fahmy', '+20100000099', 'layla@gmail.com', 'CS', '1st Year', 'ACTIVE'],
            headers=['student_id', 'email', 'first_name', 'last_name', 'phone', 'personal_email', 'department', 'academic_level', 'status']
        )

        result = resource.import_data(dataset, dry_run=False)
        assert result.has_errors() is False

        student = Student.objects.get(student_id='STU901')
        assert student.user.email == 'stu901@foe.edu'
        assert student.organization == org
        # Crucial architectural guarantee: Zero implicit enrollments!
        assert StudentEnrollment.objects.filter(student=student).count() == 0

    def test_doctor_import_provisions_account_independently(self, academic_setup):
        """Doctor import provisions doctor profile and user account independently."""
        org = academic_setup['org_a']
        resource = DoctorResource()
        resource.organization = org

        dataset = tablib.Dataset(
            ['doc_new@foe.edu', 'Hassan', 'Fathy', 'Architecture', 'Prof.'],
            headers=['email', 'first_name', 'last_name', 'department', 'title']
        )

        result = resource.import_data(dataset, dry_run=False)
        assert result.has_errors() is False

        doc = Doctor.objects.get(user__email='doc_new@foe.edu')
        assert doc.title == 'Prof.'
        assert doc.department == 'Architecture'
        assert doc.course_offerings.count() == 0

    def test_ta_import_provisions_account_independently(self, academic_setup):
        """Teaching assistant import provisions TA profile and user account independently."""
        org = academic_setup['org_a']
        resource = TeachingAssistantResource()
        resource.organization = org

        dataset = tablib.Dataset(
            ['ta_new@foe.edu', 'Youssef', 'Nabil', 'CS'],
            headers=['email', 'first_name', 'last_name', 'department']
        )

        result = resource.import_data(dataset, dry_run=False)
        assert result.has_errors() is False

        ta = TeachingAssistant.objects.get(user__email='ta_new@foe.edu')
        assert ta.department == 'CS'
        assert ta.assigned_groups.count() == 0


# ==============================================================================
# 2. StaffAssignmentService Tests
# ==============================================================================

@pytest.mark.django_db(transaction=True)
class TestStaffAssignmentService:
    """Verifies service logic for Doctor and TA assignments and reassignments."""

    def test_assign_doctor_to_new_and_reassigned_offerings(self, academic_setup):
        """Reassigning an offering from Doc 1 to Doc 2 replaces Doc 1 atomically."""
        org = academic_setup['org_a']
        doc1 = academic_setup['doc1']
        doc2 = academic_setup['doc2']
        off1 = academic_setup['offering_cs101']
        off2 = academic_setup['offering_cs102']

        # Setup: initially off1 has doc1, off2 is unassigned
        off1.doctor = doc1
        off1.save()
        off2.doctor = None
        off2.save()

        # Create schedule for off1
        sched1 = Schedule.objects.create(
            course_offering=off1,
            doctor=doc1,
            session_type=SessionType.LECTURE,
            day_of_week=0,
            start_time='09:00',
            end_time='10:30'
        )

        # Execute assignment to Doc 2
        result = StaffAssignmentService.assign_doctor_to_offerings(
            doctor=doc2,
            course_offering_ids=[off1.id, off2.id],
            organization=org,
            dry_run=False
        )

        assert result.newly_assigned_count == 1  # off2
        assert result.reassigned_count == 1      # off1 (replaced doc1)
        assert result.unchanged_count == 0
        assert result.rejected_count == 0

        # Verify DB: both offerings are now assigned to doc2
        off1.refresh_from_db()
        off2.refresh_from_db()
        assert off1.doctor == doc2
        assert off2.doctor == doc2

        # Verify schedule synchronization
        sched1.refresh_from_db()
        assert sched1.doctor == doc2

    def test_assign_doctor_dry_run_zero_writes(self, academic_setup):
        """Dry-run preview calculates replacements with zero database writes."""
        org = academic_setup['org_a']
        doc1 = academic_setup['doc1']
        doc2 = academic_setup['doc2']
        off1 = academic_setup['offering_cs101']

        off1.doctor = doc1
        off1.save()

        result = StaffAssignmentService.assign_doctor_to_offerings(
            doctor=doc2,
            course_offering_ids=[off1.id],
            organization=org,
            dry_run=True
        )

        assert result.reassigned_count == 1
        assert result.details[0]['action_type'] == 'REASSIGNED'
        assert result.details[0]['previous_doctor'] == doc1
        assert result.details[0]['new_doctor'] == doc2

        # DB must NOT be modified
        off1.refresh_from_db()
        assert off1.doctor == doc1

    def test_assign_doctor_cross_tenant_rejected(self, academic_setup):
        """Cross-tenant course offerings are rejected."""
        org = academic_setup['org_a']
        doc1 = academic_setup['doc1']
        off_b = academic_setup['offering_bio101']  # Org B

        result = StaffAssignmentService.assign_doctor_to_offerings(
            doctor=doc1,
            course_offering_ids=[off_b.id],
            organization=org,
            dry_run=False
        )

        assert result.rejected_count == 1
        assert result.newly_assigned_count == 0

        off_b.refresh_from_db()
        assert off_b.doctor is None

    def test_assign_ta_to_new_and_reassigned_groups(self, academic_setup):
        """Reassigning a group from TA 1 to TA 2 replaces TA 1 atomically."""
        org = academic_setup['org_a']
        ta1 = academic_setup['ta1']
        ta2 = academic_setup['ta2']
        g1 = academic_setup['group_sec1']
        g2 = academic_setup['group_sec2']

        # Setup: g1 has ta1, g2 is unassigned
        g1.teaching_assistant = ta1
        g1.save()
        g2.teaching_assistant = None
        g2.save()

        # Create schedule for g1
        sched = Schedule.objects.create(
            course_offering=g1.course_offering,
            group=g1,
            teaching_assistant=ta1,
            session_type=SessionType.LAB,
            day_of_week=1,
            start_time='11:00',
            end_time='13:00'
        )

        result = StaffAssignmentService.assign_ta_to_groups(
            ta=ta2,
            group_ids=[g1.id, g2.id],
            organization=org,
            dry_run=False
        )

        assert result.newly_assigned_count == 1  # g2
        assert result.reassigned_count == 1      # g1 (replaced ta1)
        assert result.unchanged_count == 0
        assert result.rejected_count == 0

        # Verify DB
        g1.refresh_from_db()
        g2.refresh_from_db()
        assert g1.teaching_assistant == ta2
        assert g2.teaching_assistant == ta2

        # Verify schedule sync
        sched.refresh_from_db()
        assert sched.teaching_assistant == ta2

    def test_assign_ta_dry_run_zero_writes(self, academic_setup):
        """TA dry-run preview calculates replacement metrics with zero database writes."""
        org = academic_setup['org_a']
        ta1 = academic_setup['ta1']
        ta2 = academic_setup['ta2']
        g1 = academic_setup['group_sec1']

        g1.teaching_assistant = ta1
        g1.save()

        result = StaffAssignmentService.assign_ta_to_groups(
            ta=ta2,
            group_ids=[g1.id],
            organization=org,
            dry_run=True
        )

        assert result.reassigned_count == 1
        assert result.details[0]['action_type'] == 'REASSIGNED'
        assert result.details[0]['previous_ta'] == ta1
        assert result.details[0]['new_ta'] == ta2

        # DB must NOT be modified
        g1.refresh_from_db()
        assert g1.teaching_assistant == ta1


# ==============================================================================
# 3. Streamlined Staff Schedule Forms Tests
# ==============================================================================

@pytest.mark.django_db(transaction=True)
class TestStreamlinedStaffScheduleForms:
    """Verifies streamlined form logic for Doctor lectures and TA labs."""

    def test_doctor_schedule_inline_form_lectures_only(self, academic_setup):
        """DoctorScheduleInlineForm auto-sets session_type=LECTURE, group=None, and doctor."""
        doc1 = academic_setup['doc1']
        off1 = academic_setup['offering_cs101']

        form_data = {
            'course_offering': off1.id,
            'room_label': 'Auditorium A',
            'day_of_week': 0,
            'start_time': '09:00',
            'end_time': '10:30',
            'effective_from': '2026-09-01',
            'effective_until': '2027-01-31',
            'is_active': True,
        }

        form = DoctorScheduleInlineForm(data=form_data)
        # Mock request with _editing_doctor
        request = RequestFactory().get('/')
        request._editing_doctor = doc1
        form.request = request

        assert form.is_valid(), form.errors
        schedule = form.save()

        assert schedule.session_type == SessionType.LECTURE
        assert schedule.group is None
        assert schedule.doctor == doc1
        assert schedule.room_label == 'Auditorium A'

    def test_ta_schedule_inline_form_labs_only(self, academic_setup):
        """TAScheduleInlineForm auto-sets session_type=LAB and teaching_assistant."""
        ta1 = academic_setup['ta1']
        off1 = academic_setup['offering_cs101']
        g1 = academic_setup['group_sec1']

        form_data = {
            'course_offering': off1.id,
            'group': g1.id,
            'day_of_week': 2,
            'start_time': '12:00',
            'end_time': '14:00',
            'is_active': True,
        }

        form = TAScheduleInlineForm(data=form_data)
        request = RequestFactory().get('/')
        request._editing_ta = ta1
        form.request = request

        assert form.is_valid(), form.errors
        schedule = form.save()

        assert schedule.session_type == SessionType.LAB
        assert schedule.teaching_assistant == ta1
        assert schedule.group == g1

    def test_ta_schedule_inline_form_rejects_mismatched_group(self, academic_setup):
        """TAScheduleInlineForm rejects groups that do not belong to the selected course offering."""
        ta1 = academic_setup['ta1']
        off2 = academic_setup['offering_cs102']
        g1 = academic_setup['group_sec1']  # belongs to off1, NOT off2

        form_data = {
            'course_offering': off2.id,
            'group': g1.id,
            'day_of_week': 1,
            'start_time': '10:00',
            'end_time': '12:00',
            'is_active': True,
        }

        form = TAScheduleInlineForm(data=form_data)
        request = RequestFactory().get('/')
        request._editing_ta = ta1
        form.request = request

        assert not form.is_valid()
        assert 'group' in form.errors
        assert "does not belong to" in str(form.errors['group'])


# ==============================================================================
# 4. Inlines & Direct Shortcut URLs Tests (Option 1 & Option 2)
# ==============================================================================

@pytest.mark.django_db(transaction=True)
class TestStaffAdminInlinesAndShortcuts:
    """Verifies that inlines prevent inline creation and detail pages provide shortcut buttons."""

    def test_inlines_prevent_inline_creation(self):
        """CourseOfferingInline and AssignedGroupInline disable add permission and set extra=0."""
        from django.contrib.admin.sites import AdminSite
        site = AdminSite()
        course_inline = CourseOfferingInline(Doctor, site)
        assert course_inline.has_add_permission(None) is False
        assert course_inline.extra == 0

        group_inline = AssignedGroupInline(TeachingAssistant, site)
        assert group_inline.has_add_permission(None) is False
        assert group_inline.extra == 0

    def test_doctor_detail_page_has_direct_assign_button(self, academic_setup):
        """Doctor change form includes the direct 'Assign Courses' shortcut button."""
        client = Client()
        client.force_login(academic_setup['admin_a'])
        doc1 = academic_setup['doc1']

        response = client.get(f'/admin/staff/doctor/{doc1.id}/change/')
        assert response.status_code == 200
        content = response.content.decode()
        assert f"/admin/staff/doctor/{doc1.id}/assign-courses/" in content
        assert "Assign Courses" in content

    def test_ta_detail_page_has_direct_assign_button(self, academic_setup):
        """Teaching Assistant change form includes the direct 'Allocate Existing Groups' shortcut button."""
        client = Client()
        client.force_login(academic_setup['admin_a'])
        ta1 = academic_setup['ta1']

        response = client.get(f'/admin/staff/teachingassistant/{ta1.id}/change/')
        assert response.status_code == 200
        content = response.content.decode()
        assert f"/admin/staff/teachingassistant/{ta1.id}/assign-groups/" in content
        assert "Allocate Existing Groups" in content

    def test_doctor_direct_assign_url_loads(self, academic_setup):
        """Direct URL /admin/staff/doctor/<id>/assign-courses/ renders course assignment form."""
        client = Client()
        client.force_login(academic_setup['admin_a'])
        doc1 = academic_setup['doc1']

        response = client.get(f'/admin/staff/doctor/{doc1.id}/assign-courses/')
        assert response.status_code == 200
        content = response.content.decode()
        assert "Assign Course Offerings to Doctor" in content
        assert "CS101" in content

    def test_ta_direct_assign_url_loads(self, academic_setup):
        """Direct URL /admin/staff/teachingassistant/<id>/assign-groups/ renders course-driven group allocation form."""
        client = Client()
        client.force_login(academic_setup['admin_a'])
        ta1 = academic_setup['ta1']

        response = client.get(f'/admin/staff/teachingassistant/{ta1.id}/assign-groups/')
        assert response.status_code == 200
        content = response.content.decode()
        assert "Allocate Existing Sections & Groups to Teaching Assistant" in content
        assert "Choose Course Offering" in content
        assert "CS101" in content
        assert "Section 1" in content


# ==============================================================================
# 5. Admin Integration Tests (DoctorAdmin & TeachingAssistantAdmin Multi-Step)
# ==============================================================================

@pytest.mark.django_db(transaction=True)
class TestStaffAdminIntegration:
    """Verifies Django Admin multi-step action workflows for Doctors and TAs."""

    def test_doctor_admin_action_renders_form(self, academic_setup):
        """DoctorAdmin assign_courses_to_doctor renders active offerings for organization."""
        client = Client()
        client.force_login(academic_setup['admin_a'])
        doc1 = academic_setup['doc1']

        response = client.post(
            '/admin/staff/doctor/',
            {
                'action': 'assign_courses_to_doctor',
                '_selected_action': [doc1.id]
            }
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert "Assign Course Offerings to Doctor" in content
        assert "CS101" in content
        assert "CS102" in content

    def test_doctor_admin_preview_and_confirm_workflow(self, academic_setup):
        """DoctorAdmin dry-run preview and confirmation commit replaces previous doctor."""
        client = Client()
        client.force_login(academic_setup['admin_a'])
        doc1 = academic_setup['doc1']
        doc2 = academic_setup['doc2']
        off1 = academic_setup['offering_cs101']

        off1.doctor = doc1
        off1.save()

        # Step 2: Preview
        response_preview = client.post(
            '/admin/staff/doctor/',
            {
                'action': 'assign_courses_to_doctor',
                '_selected_action': [doc2.id],
                'action_step': 'preview',
                'course_offerings': [off1.id],
            }
        )
        assert response_preview.status_code == 200
        content_preview = response_preview.content.decode()
        assert "Review Proposed Course Assignments for Doctor" in content_preview
        assert "Reassigned (Transferred)" in content_preview
        # Zero writes during preview
        off1.refresh_from_db()
        assert off1.doctor == doc1

        # Step 3: Confirm
        response_confirm = client.post(
            '/admin/staff/doctor/',
            {
                'action': 'assign_courses_to_doctor',
                '_selected_action': [doc2.id],
                'action_step': 'confirm',
                'course_offerings': [off1.id],
            },
            follow=True
        )
        assert response_confirm.status_code == 200
        messages = [m.message for m in response_confirm.context['messages']]
        assert any("Course assignment complete for" in m and "reassigned (previous doctors replaced)" in m for m in messages)

        # Database updated
        off1.refresh_from_db()
        assert off1.doctor == doc2

    def test_ta_admin_action_renders_course_driven_form(self, academic_setup):
        """TeachingAssistantAdmin assign_groups_to_ta renders course-driven sections for organization."""
        client = Client()
        client.force_login(academic_setup['admin_a'])
        ta1 = academic_setup['ta1']

        response = client.post(
            '/admin/staff/teachingassistant/',
            {
                'action': 'assign_groups_to_ta',
                '_selected_action': [ta1.id]
            }
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert "Allocate Existing Sections & Groups to Teaching Assistant" in content
        assert "Choose Course Offering" in content
        assert "Section 1" in content

    def test_ta_admin_preview_and_confirm_workflow(self, academic_setup):
        """TeachingAssistantAdmin preview and confirmation commit replaces previous TA."""
        client = Client()
        client.force_login(academic_setup['admin_a'])
        ta1 = academic_setup['ta1']
        ta2 = academic_setup['ta2']
        g1 = academic_setup['group_sec1']

        g1.teaching_assistant = ta1
        g1.save()

        # Step 2: Preview
        response_preview = client.post(
            '/admin/staff/teachingassistant/',
            {
                'action': 'assign_groups_to_ta',
                '_selected_action': [ta2.id],
                'action_step': 'preview',
                'groups': [g1.id],
            }
        )
        assert response_preview.status_code == 200
        content_preview = response_preview.content.decode()
        assert "Review Proposed Section / Group Assignments for TA" in content_preview
        # Zero writes during preview
        g1.refresh_from_db()
        assert g1.teaching_assistant == ta1

        # Step 3: Confirm
        response_confirm = client.post(
            '/admin/staff/teachingassistant/',
            {
                'action': 'assign_groups_to_ta',
                '_selected_action': [ta2.id],
                'action_step': 'confirm',
                'groups': [g1.id],
            },
            follow=True
        )
        assert response_confirm.status_code == 200
        messages = [m.message for m in response_confirm.context['messages']]
        assert any("Group assignment complete for TA" in m and "reassigned (previous TAs replaced)" in m for m in messages)

        # Database updated
        g1.refresh_from_db()
        assert g1.teaching_assistant == ta2

    def test_doctor_schedule_inline_filters_out_lab_schedules(self, academic_setup):
        """DoctorScheduleInline strictly filters out LAB sessions, returning LECTURE only."""
        from django.contrib.admin.sites import AdminSite
        doc1 = academic_setup['doc1']
        off1 = academic_setup['offering_cs101']

        lecture = Schedule.objects.create(
            course_offering=off1,
            doctor=doc1,
            session_type=SessionType.LECTURE,
            day_of_week=0,
            start_time='09:00',
            end_time='10:30'
        )
        lab = Schedule.objects.create(
            course_offering=off1,
            doctor=doc1,
            session_type=SessionType.LAB,
            day_of_week=1,
            start_time='11:00',
            end_time='13:00'
        )

        inline = DoctorScheduleInline(Doctor, AdminSite())
        request = RequestFactory().get('/')
        request.user = academic_setup['admin_a']
        request._editing_doctor = doc1
        qs = inline.get_queryset(request).filter(doctor=doc1)

        assert lecture in qs
        assert lab not in qs

    def test_ta_schedule_inline_filters_out_lecture_schedules(self, academic_setup):
        """TAScheduleInline strictly filters out LECTURE sessions, returning LAB only."""
        from django.contrib.admin.sites import AdminSite
        ta1 = academic_setup['ta1']
        off1 = academic_setup['offering_cs101']
        g1 = academic_setup['group_sec1']

        lecture = Schedule.objects.create(
            course_offering=off1,
            teaching_assistant=ta1,
            session_type=SessionType.LECTURE,
            day_of_week=0,
            start_time='09:00',
            end_time='10:30'
        )
        lab = Schedule.objects.create(
            course_offering=off1,
            group=g1,
            teaching_assistant=ta1,
            session_type=SessionType.LAB,
            day_of_week=1,
            start_time='11:00',
            end_time='13:00'
        )

        inline = TAScheduleInline(TeachingAssistant, AdminSite())
        request = RequestFactory().get('/')
        request.user = academic_setup['admin_a']
        request._editing_ta = ta1
        qs = inline.get_queryset(request).filter(teaching_assistant=ta1)

        assert lab in qs
        assert lecture not in qs

    def test_group_admin_bulk_reassign_ta_workflow(self, academic_setup):
        """GroupAdmin.reassign_ta preview and confirm workflow reassigns multiple groups atomically."""
        client = Client()
        client.force_login(academic_setup['admin_a'])
        ta1 = academic_setup['ta1']
        ta2 = academic_setup['ta2']
        g1 = academic_setup['group_sec1']
        g2 = academic_setup['group_sec2']

        g1.teaching_assistant = ta1
        g1.save()
        g2.teaching_assistant = None
        g2.save()

        # Step 2: Preview
        response_preview = client.post(
            '/admin/groups/group/',
            {
                'action': 'reassign_ta',
                '_selected_action': [g1.id, g2.id],
                'action_step': 'preview',
                'new_ta': ta2.id,
            }
        )
        assert response_preview.status_code == 200
        content_preview = response_preview.content.decode()
        assert "Review Proposed Section / Group Assignments" in content_preview
        assert "Reassigned (Transferred)" in content_preview

        # Zero DB writes on preview
        g1.refresh_from_db()
        assert g1.teaching_assistant == ta1

        # Step 3: Confirm
        response_confirm = client.post(
            '/admin/groups/group/',
            {
                'action': 'reassign_ta',
                '_selected_action': [g1.id, g2.id],
                'action_step': 'confirm',
                'new_ta': ta2.id,
            },
            follow=True
        )
        assert response_confirm.status_code == 200
        messages = [m.message for m in response_confirm.context['messages']]
        assert any("Successfully assigned 2 groups to TA" in m for m in messages)

        # Database updated atomically
        g1.refresh_from_db()
        g2.refresh_from_db()
        assert g1.teaching_assistant == ta2
        assert g2.teaching_assistant == ta2
