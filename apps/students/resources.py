"""
django-import-export resources for Students and StudentEnrollments.
"""

import logging
from django.db import transaction
from django.core.exceptions import ValidationError
from import_export import fields
from apps.accounts.models import Role
from apps.accounts.resources import OrgScopedModelResource
from apps.accounts.services.member_provisioning import MemberProvisioningService
from apps.students.models import Student, StudentEnrollment
from apps.courses.models import CourseOffering
from apps.groups.models import Group

logger = logging.getLogger(__name__)


class StudentResource(OrgScopedModelResource):
    student_id = fields.Field(column_name='student_id', attribute='student_id')
    email = fields.Field(column_name='email')
    first_name = fields.Field(column_name='first_name')
    last_name = fields.Field(column_name='last_name')
    phone = fields.Field(column_name='phone', attribute='phone')
    personal_email = fields.Field(column_name='personal_email', attribute='personal_email')
    department = fields.Field(column_name='department', attribute='department')
    academic_level = fields.Field(column_name='academic_level', attribute='academic_level')
    status = fields.Field(column_name='status', attribute='status')

    class Meta(OrgScopedModelResource.Meta):
        model = Student
        import_id_fields = ['student_id']
        fields = [
            'student_id', 'email', 'first_name', 'last_name',
            'phone', 'personal_email', 'department', 'academic_level', 'status'
        ]
        export_order = fields

    def get_instance(self, instance_loader, row):
        student_id = row.get('student_id')
        if not student_id:
            return None
        return self.get_queryset().filter(student_id=str(student_id).strip()).first()

    def before_save_instance(self, instance, row, **kwargs):
        super().before_save_instance(instance, row, **kwargs)
        raw_email = row.get('email')
        raw_first_name = row.get('first_name')
        raw_last_name = row.get('last_name')

        if not raw_email or not str(raw_email).strip():
            raise ValidationError("Email is required for student import.")
        if not raw_first_name or not str(raw_first_name).strip():
            raise ValidationError("First name is required for student import.")
        if not raw_last_name or not str(raw_last_name).strip():
            raise ValidationError("Last name is required for student import.")

        row_email = str(raw_email).strip().lower()
        row_first_name = str(raw_first_name).strip()
        row_last_name = str(raw_last_name).strip()

        # CASE A: Existing Student Profile
        if instance.pk is not None:
            existing_user = instance.user
            if existing_user.email.lower() != row_email:
                raise ValidationError(
                    f"Student ID '{instance.student_id}' is permanently linked to '{existing_user.email}'. "
                    f"Changing emails via bulk import is prohibited. Use manual administrative transfer."
                )
            existing_user.first_name = row_first_name
            existing_user.last_name = row_last_name
            existing_user.save(update_fields=['first_name', 'last_name', 'updated_at'])
            instance._is_new_user = False

        # CASE B: New Student Profile
        else:
            if not getattr(instance, '_user_attached', False):
                student_id = str(row.get('student_id') or instance.student_id or '').strip()
                org_slug = getattr(self.organization, 'slug', 'org')
                policy = getattr(self.organization, 'provisioning_policy', None)
                if not policy and hasattr(self.organization, 'get_provisioning_policy'):
                    policy = self.organization.get_provisioning_policy()

                try:
                    password = policy.password_pattern.format(student_id=student_id, org_slug=org_slug)
                except Exception:
                    password = f"{student_id}#{org_slug}!"

                user, is_new = MemberProvisioningService.get_or_create_member_user(
                    organization=self.organization,
                    email=row_email,
                    first_name=row_first_name,
                    last_name=row_last_name,
                    role=Role.STUDENT,
                    password=password,
                )
                if not is_new and hasattr(user, 'student_profile') and user.student_profile.pk != instance.pk:
                    raise ValidationError(
                        f"User '{row_email}' is already associated with Student ID '{user.student_profile.student_id}'."
                    )
                instance.user = user
                instance.organization = self.organization
                instance._is_new_user = is_new
                instance._user_attached = True

        if row.get('phone') is not None:
            instance.phone = str(row['phone']).strip()
        if row.get('personal_email') is not None:
            instance.personal_email = str(row['personal_email']).strip().lower() if row['personal_email'] else None
        if row.get('department') is not None:
            instance.department = str(row['department']).strip()
        if row.get('academic_level') is not None:
            instance.academic_level = str(row['academic_level']).strip()
        if row.get('status') is not None and str(row['status']).strip():
            instance.status = str(row['status']).strip()

    def after_save_instance(self, instance, row, **kwargs):
        super().after_save_instance(instance, row, **kwargs)
        dry_run = kwargs.get('dry_run', False)
        if not dry_run and getattr(instance, '_is_new_user', False):
            user_id = instance.user_id
            def dispatch_activation():
                try:
                    MemberProvisioningService.send_activation_email(user_id)
                except Exception as e:
                    logger.error(f"Failed to dispatch activation email to student user {user_id}: {e}")
            transaction.on_commit(dispatch_activation)

    def dehydrate_email(self, obj):
        return obj.user.email if obj.user else ''

    def dehydrate_first_name(self, obj):
        return obj.user.first_name if obj.user else ''

    def dehydrate_last_name(self, obj):
        return obj.user.last_name if obj.user else ''


class StudentEnrollmentResource(OrgScopedModelResource):
    org_field_lookup = 'course_offering__course__organization'

    student_id = fields.Field(column_name='student_id')
    course_code = fields.Field(column_name='course_code')
    academic_year = fields.Field(column_name='academic_year')
    semester = fields.Field(column_name='semester')
    group_name = fields.Field(column_name='group_name')

    class Meta(OrgScopedModelResource.Meta):
        model = StudentEnrollment
        fields = ['student_id', 'course_code', 'academic_year', 'semester', 'group_name']
        export_order = fields

    def get_instance(self, instance_loader, row):
        student_id = row.get('student_id')
        course_code = row.get('course_code')
        year_name = row.get('academic_year')
        sem_name = row.get('semester')

        if not (student_id and course_code and year_name and sem_name):
            return None

        student = Student.objects.filter(
            organization=self.organization,
            student_id=str(student_id).strip()
        ).first()

        offering = CourseOffering.objects.filter(
            course__organization=self.organization,
            course__code=str(course_code).strip(),
            academic_year__name=str(year_name).strip(),
            semester__name=str(sem_name).strip()
        ).first()

        if student and offering:
            return StudentEnrollment.objects.filter(student=student, course_offering=offering).first()
        return None

    def init_instance(self, row=None):
        return StudentEnrollment()

    def before_save_instance(self, instance, row, **kwargs):
        super().before_save_instance(instance, row, **kwargs)
        student_id = str(row.get('student_id', '')).strip()
        course_code = str(row.get('course_code', '')).strip()
        year_name = str(row.get('academic_year', '')).strip()
        sem_name = str(row.get('semester', '')).strip()
        group_name = str(row.get('group_name', '')).strip() if row.get('group_name') else None

        student = Student.objects.filter(organization=self.organization, student_id=student_id).first()
        if not student:
            raise ValidationError(f"Student with ID '{student_id}' does not exist in this organization.")

        offering = CourseOffering.objects.filter(
            course__organization=self.organization,
            course__code=course_code,
            academic_year__name=year_name,
            semester__name=sem_name
        ).first()
        if not offering:
            raise ValidationError(f"Course Offering '{course_code} ({year_name} - {sem_name})' does not exist in this organization.")

        instance.student = student
        instance.course_offering = offering

        if group_name:
            group = Group.objects.filter(course_offering=offering, name=group_name).first()
            if not group:
                raise ValidationError(f"Group '{group_name}' does not belong to course offering '{course_code}'.")
            instance.group = group
        else:
            instance.group = None

    def dehydrate_student_id(self, obj):
        return obj.student.student_id if obj.student else ''

    def dehydrate_course_code(self, obj):
        return obj.course_offering.course.code if obj.course_offering and obj.course_offering.course else ''

    def dehydrate_academic_year(self, obj):
        return obj.course_offering.academic_year.name if obj.course_offering and obj.course_offering.academic_year else ''

    def dehydrate_semester(self, obj):
        return obj.course_offering.semester.name if obj.course_offering and obj.course_offering.semester else ''

    def dehydrate_group_name(self, obj):
        return obj.group.name if obj.group else ''

