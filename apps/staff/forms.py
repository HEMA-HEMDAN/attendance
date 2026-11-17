"""
Staff Admin Forms — unified single-form creation for Doctor and TeachingAssistant.
"""

from django import forms
from django.db import transaction
from apps.accounts.models import Role
from apps.accounts.services.member_provisioning import MemberProvisioningService
from apps.organizations.models import Organization, OrganizationStatus
from .models import Doctor, TeachingAssistant


class DoctorAdminForm(forms.ModelForm):
    organization = forms.ModelChoiceField(
        queryset=Organization.objects.filter(status=OrganizationStatus.ACTIVE),
        required=False,
        help_text="Organization for this doctor (required for superadmins)."
    )
    email = forms.EmailField(required=True, help_text="Login email address.")
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)

    class Meta:
        model = Doctor
        fields = ['organization', 'email', 'first_name', 'last_name', 'title', 'department']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if hasattr(self, 'request') and not self.request.user.is_superuser:
            self.fields['organization'].widget = forms.HiddenInput()
            self.fields['organization'].required = False
        if self.instance and self.instance.pk and hasattr(self.instance, 'user') and self.instance.user:
            self.fields['email'].initial = self.instance.user.email
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name
            self.fields['email'].disabled = True

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if self.instance and self.instance.pk and hasattr(self.instance, 'user') and self.instance.user:
            if self.instance.user.email.lower() != email:
                raise forms.ValidationError("Changing email is prohibited.")
        return email

    @transaction.atomic
    def save(self, commit=True):
        email = self.cleaned_data['email'].strip().lower()
        first_name = self.cleaned_data['first_name'].strip()
        last_name = self.cleaned_data['last_name'].strip()

        if self.instance and self.instance.pk and hasattr(self.instance, 'user') and self.instance.user:
            user = self.instance.user
            user.first_name = first_name
            user.last_name = last_name
            user.save(update_fields=['first_name', 'last_name', 'updated_at'])
        else:
            org = getattr(self.instance, 'organization', None) or self.cleaned_data.get('organization')
            if not org and hasattr(self, 'request') and self.request:
                org = self.request.user.organization
            if not org:
                raise forms.ValidationError("Target organization is required.")
            self.instance.organization = org

            user, is_new = MemberProvisioningService.get_or_create_member_user(
                organization=org,
                email=email,
                first_name=first_name,
                last_name=last_name,
                role=Role.DOCTOR,
            )
            if not is_new and hasattr(user, 'doctor_profile') and user.doctor_profile.pk != self.instance.pk:
                raise forms.ValidationError(f"User '{email}' is already associated with a Doctor profile.")

            if is_new:
                user_id = user.id
                transaction.on_commit(lambda: MemberProvisioningService.send_activation_email(user_id))
            self.instance.user = user

        return super().save(commit=commit)


class TeachingAssistantAdminForm(forms.ModelForm):
    organization = forms.ModelChoiceField(
        queryset=Organization.objects.filter(status=OrganizationStatus.ACTIVE),
        required=False,
        help_text="Organization for this TA (required for superadmins)."
    )
    email = forms.EmailField(required=True, help_text="Login email address.")
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)

    class Meta:
        model = TeachingAssistant
        fields = ['organization', 'email', 'first_name', 'last_name', 'department']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if hasattr(self, 'request') and not self.request.user.is_superuser:
            self.fields['organization'].widget = forms.HiddenInput()
            self.fields['organization'].required = False
        if self.instance and self.instance.pk and hasattr(self.instance, 'user') and self.instance.user:
            self.fields['email'].initial = self.instance.user.email
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name
            self.fields['email'].disabled = True

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if self.instance and self.instance.pk and hasattr(self.instance, 'user') and self.instance.user:
            if self.instance.user.email.lower() != email:
                raise forms.ValidationError("Changing email is prohibited.")
        return email

    @transaction.atomic
    def save(self, commit=True):
        email = self.cleaned_data['email'].strip().lower()
        first_name = self.cleaned_data['first_name'].strip()
        last_name = self.cleaned_data['last_name'].strip()

        if self.instance and self.instance.pk and hasattr(self.instance, 'user') and self.instance.user:
            user = self.instance.user
            user.first_name = first_name
            user.last_name = last_name
            user.save(update_fields=['first_name', 'last_name', 'updated_at'])
        else:
            org = getattr(self.instance, 'organization', None) or self.cleaned_data.get('organization')
            if not org and hasattr(self, 'request') and self.request:
                org = self.request.user.organization
            if not org:
                raise forms.ValidationError("Target organization is required.")
            self.instance.organization = org

            user, is_new = MemberProvisioningService.get_or_create_member_user(
                organization=org,
                email=email,
                first_name=first_name,
                last_name=last_name,
                role=Role.TEACHING_ASSISTANT,
            )
            if not is_new and hasattr(user, 'ta_profile') and user.ta_profile.pk != self.instance.pk:
                raise forms.ValidationError(f"User '{email}' is already associated with a TA profile.")

            if is_new:
                user_id = user.id
                transaction.on_commit(lambda: MemberProvisioningService.send_activation_email(user_id))
            self.instance.user = user

        return super().save(commit=commit)


class DoctorScheduleInlineForm(forms.ModelForm):
    """
    Streamlined schedule form for Doctors:
    - Dedicated to LECTURES (session_type auto-set to LECTURE, group is None).
    - Visible fields: course_offering, room_label, day_of_week, start_time, end_time, effective_from, effective_until, is_active.
    - Stripped: no group, no teaching_assistant, no location dropdown.
    """
    class Meta:
        from apps.courses.models import Schedule
        model = Schedule
        fields = [
            'course_offering', 'room_label', 'day_of_week',
            'start_time', 'end_time', 'effective_from', 'effective_until', 'is_active'
        ]

    def clean(self):
        from apps.courses.models import SessionType
        cleaned_data = super().clean()
        self.instance.session_type = SessionType.LECTURE
        self.instance.group = None
        if hasattr(self, 'request') and getattr(self.request, '_editing_doctor', None):
            self.instance.doctor = self.request._editing_doctor
        return cleaned_data

    def save(self, commit=True):
        from apps.courses.models import SessionType
        self.instance.session_type = SessionType.LECTURE
        self.instance.group = None
        if hasattr(self, 'request') and getattr(self.request, '_editing_doctor', None):
            self.instance.doctor = self.request._editing_doctor
        return super().save(commit=commit)


class TAScheduleInlineForm(forms.ModelForm):
    """
    Streamlined schedule form for Teaching Assistants:
    - Dedicated to LABS / SECTIONS (session_type auto-set to LAB).
    - Visible fields: course_offering, group, day_of_week, start_time, end_time, is_active.
    - Stripped: no doctor, no location dropdown.
    """
    class Meta:
        from apps.courses.models import Schedule
        model = Schedule
        fields = [
            'course_offering', 'group', 'day_of_week',
            'start_time', 'end_time', 'is_active'
        ]

    def clean(self):
        from apps.courses.models import SessionType
        cleaned_data = super().clean()
        self.instance.session_type = SessionType.LAB
        if hasattr(self, 'request') and getattr(self.request, '_editing_ta', None):
            self.instance.teaching_assistant = self.request._editing_ta
        group = cleaned_data.get('group')
        course_offering = cleaned_data.get('course_offering')
        if group and course_offering:
            if group.course_offering_id != course_offering.id:
                self.add_error('group', f"Group '{group.name}' does not belong to '{course_offering}'.")
        return cleaned_data

    def save(self, commit=True):
        from apps.courses.models import SessionType
        self.instance.session_type = SessionType.LAB
        if hasattr(self, 'request') and getattr(self.request, '_editing_ta', None):
            self.instance.teaching_assistant = self.request._editing_ta
        return super().save(commit=commit)

