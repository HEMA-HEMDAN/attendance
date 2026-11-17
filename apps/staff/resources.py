"""
django-import-export resources for Staff (Doctor, TeachingAssistant).
"""

import logging
from django.db import transaction
from django.core.exceptions import ValidationError
from import_export import fields
from apps.accounts.models import Role
from apps.accounts.resources import OrgScopedModelResource
from apps.accounts.services.member_provisioning import MemberProvisioningService
from apps.staff.models import Doctor, TeachingAssistant

logger = logging.getLogger(__name__)


class DoctorResource(OrgScopedModelResource):
    email = fields.Field(column_name='email')
    first_name = fields.Field(column_name='first_name')
    last_name = fields.Field(column_name='last_name')
    department = fields.Field(column_name='department', attribute='department')
    title = fields.Field(column_name='title', attribute='title')

    class Meta(OrgScopedModelResource.Meta):
        model = Doctor
        fields = ['email', 'first_name', 'last_name', 'department', 'title']
        export_order = fields

    def get_instance(self, instance_loader, row):
        email = row.get('email')
        if not email:
            return None
        return Doctor.objects.filter(
            organization=self.organization,
            user__email=str(email).strip().lower()
        ).first()

    def before_save_instance(self, instance, row, **kwargs):
        super().before_save_instance(instance, row, **kwargs)
        raw_email = row.get('email')
        raw_first_name = row.get('first_name')
        raw_last_name = row.get('last_name')

        if not raw_email or not str(raw_email).strip():
            raise ValidationError("Email is required for doctor import.")
        if not raw_first_name or not str(raw_first_name).strip():
            raise ValidationError("First name is required for doctor import.")
        if not raw_last_name or not str(raw_last_name).strip():
            raise ValidationError("Last name is required for doctor import.")

        row_email = str(raw_email).strip().lower()
        row_first_name = str(raw_first_name).strip()
        row_last_name = str(raw_last_name).strip()

        if instance.pk is not None:
            existing_user = instance.user
            if existing_user.email.lower() != row_email:
                raise ValidationError(
                    f"Doctor profile is permanently linked to '{existing_user.email}'. "
                    f"Changing emails via bulk import is prohibited."
                )
            existing_user.first_name = row_first_name
            existing_user.last_name = row_last_name
            existing_user.save(update_fields=['first_name', 'last_name', 'updated_at'])
            instance._is_new_user = False
        else:
            if not getattr(instance, '_user_attached', False):
                user, is_new = MemberProvisioningService.get_or_create_member_user(
                    organization=self.organization,
                    email=row_email,
                    first_name=row_first_name,
                    last_name=row_last_name,
                    role=Role.DOCTOR,
                )
                if not is_new and hasattr(user, 'doctor_profile') and user.doctor_profile.pk != instance.pk:
                    raise ValidationError(f"User '{row_email}' is already associated with a Doctor profile.")
                instance.user = user
                instance.organization = self.organization
                instance._is_new_user = is_new
                instance._user_attached = True

        if row.get('department') is not None:
            instance.department = str(row['department']).strip()
        if row.get('title') is not None:
            instance.title = str(row['title']).strip()

    def after_save_instance(self, instance, row, **kwargs):
        super().after_save_instance(instance, row, **kwargs)
        dry_run = kwargs.get('dry_run', False)
        if not dry_run and getattr(instance, '_is_new_user', False):
            user_id = instance.user_id
            def dispatch_activation():
                try:
                    MemberProvisioningService.send_activation_email(user_id)
                except Exception as e:
                    logger.error(f"Failed to dispatch activation email to doctor user {user_id}: {e}")
            transaction.on_commit(dispatch_activation)

    def dehydrate_email(self, obj):
        return obj.user.email if obj.user else ''

    def dehydrate_first_name(self, obj):
        return obj.user.first_name if obj.user else ''

    def dehydrate_last_name(self, obj):
        return obj.user.last_name if obj.user else ''


class TeachingAssistantResource(OrgScopedModelResource):
    email = fields.Field(column_name='email')
    first_name = fields.Field(column_name='first_name')
    last_name = fields.Field(column_name='last_name')
    department = fields.Field(column_name='department', attribute='department')

    class Meta(OrgScopedModelResource.Meta):
        model = TeachingAssistant
        fields = ['email', 'first_name', 'last_name', 'department']
        export_order = fields

    def get_instance(self, instance_loader, row):
        email = row.get('email')
        if not email:
            return None
        return TeachingAssistant.objects.filter(
            organization=self.organization,
            user__email=str(email).strip().lower()
        ).first()

    def before_save_instance(self, instance, row, **kwargs):
        super().before_save_instance(instance, row, **kwargs)
        raw_email = row.get('email')
        raw_first_name = row.get('first_name')
        raw_last_name = row.get('last_name')

        if not raw_email or not str(raw_email).strip():
            raise ValidationError("Email is required for TA import.")
        if not raw_first_name or not str(raw_first_name).strip():
            raise ValidationError("First name is required for TA import.")
        if not raw_last_name or not str(raw_last_name).strip():
            raise ValidationError("Last name is required for TA import.")

        row_email = str(raw_email).strip().lower()
        row_first_name = str(raw_first_name).strip()
        row_last_name = str(raw_last_name).strip()

        if instance.pk is not None:
            existing_user = instance.user
            if existing_user.email.lower() != row_email:
                raise ValidationError(
                    f"Teaching Assistant profile is permanently linked to '{existing_user.email}'. "
                    f"Changing emails via bulk import is prohibited."
                )
            existing_user.first_name = row_first_name
            existing_user.last_name = row_last_name
            existing_user.save(update_fields=['first_name', 'last_name', 'updated_at'])
            instance._is_new_user = False
        else:
            if not getattr(instance, '_user_attached', False):
                user, is_new = MemberProvisioningService.get_or_create_member_user(
                    organization=self.organization,
                    email=row_email,
                    first_name=row_first_name,
                    last_name=row_last_name,
                    role=Role.TEACHING_ASSISTANT,
                )
                if not is_new and hasattr(user, 'ta_profile') and user.ta_profile.pk != instance.pk:
                    raise ValidationError(f"User '{row_email}' is already associated with a TA profile.")
                instance.user = user
                instance.organization = self.organization
                instance._is_new_user = is_new
                instance._user_attached = True

        if row.get('department') is not None:
            instance.department = str(row['department']).strip()

    def after_save_instance(self, instance, row, **kwargs):
        super().after_save_instance(instance, row, **kwargs)
        dry_run = kwargs.get('dry_run', False)
        if not dry_run and getattr(instance, '_is_new_user', False):
            user_id = instance.user_id
            def dispatch_activation():
                try:
                    MemberProvisioningService.send_activation_email(user_id)
                except Exception as e:
                    logger.error(f"Failed to dispatch activation email to TA user {user_id}: {e}")
            transaction.on_commit(dispatch_activation)

    def dehydrate_email(self, obj):
        return obj.user.email if obj.user else ''

    def dehydrate_first_name(self, obj):
        return obj.user.first_name if obj.user else ''

    def dehydrate_last_name(self, obj):
        return obj.user.last_name if obj.user else ''
