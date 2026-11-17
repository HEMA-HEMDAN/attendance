"""
Forms for Student administration, bulk import, and batch enrollment.
"""

from django import forms
from django.db import transaction
from apps.accounts.models import Role
from apps.accounts.services.member_provisioning import MemberProvisioningService
from apps.organizations.models import Organization, OrganizationStatus
from apps.courses.forms import GroupSelectWidget
from apps.courses.models import CourseOffering, Semester
from apps.groups.models import Group
from .models import Student, StudentStatus, StudentEnrollment


class StudentAdminForm(forms.ModelForm):
    organization = forms.ModelChoiceField(
        queryset=Organization.objects.filter(status=OrganizationStatus.ACTIVE),
        required=False,
        help_text="Target organization for this student (required for superadmins)."
    )
    email = forms.EmailField(
        required=True,
        help_text="Login email address for the student."
    )
    first_name = forms.CharField(
        max_length=150,
        required=True,
        help_text="Student's first name."
    )
    last_name = forms.CharField(
        max_length=150,
        required=True,
        help_text="Student's last name."
    )

    class Meta:
        model = Student
        fields = [
            'organization', 'student_id', 'email', 'first_name', 'last_name',
            'phone', 'personal_email', 'department', 'academic_level', 'status'
        ]

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
                raise forms.ValidationError("Changing student email is prohibited.")
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

            student_id = str(self.cleaned_data.get('student_id') or getattr(self.instance, 'student_id', '') or '').strip()
            org_slug = getattr(org, 'slug', 'org')
            policy = getattr(org, 'provisioning_policy', None)
            if not policy and hasattr(org, 'get_provisioning_policy'):
                policy = org.get_provisioning_policy()

            try:
                password = policy.password_pattern.format(student_id=student_id, org_slug=org_slug)
            except Exception:
                password = f"{student_id}#{org_slug}!"

            user, is_new = MemberProvisioningService.get_or_create_member_user(
                organization=org,
                email=email,
                first_name=first_name,
                last_name=last_name,
                role=Role.STUDENT,
                password=password,
            )
            if not is_new and hasattr(user, 'student_profile') and user.student_profile.pk != self.instance.pk:
                raise forms.ValidationError(f"User '{email}' is already associated with Student ID '{user.student_profile.student_id}'.")

            if is_new:
                user_id = user.id
                transaction.on_commit(lambda: MemberProvisioningService.send_activation_email(user_id))
            self.instance.user = user

        return super().save(commit=commit)


class StudentEnrollmentAdminForm(forms.ModelForm):
    class Meta:
        model = StudentEnrollment
        fields = '__all__'
        widgets = {
            'group': GroupSelectWidget(),
        }

    def clean(self):
        cleaned_data = super().clean()
        group = cleaned_data.get('group')
        course_offering = cleaned_data.get('course_offering')
        if group and course_offering and group.course_offering != course_offering:
            raise forms.ValidationError(
                f"Selected group '{group.name}' does not belong to course offering '{course_offering}'."
            )
        return cleaned_data


class StudentBulkImportForm(forms.Form):
    file = forms.FileField(
        label="Spreadsheet File (.xlsx or .csv)",
        widget=forms.FileInput(attrs={
            'accept': '.xlsx, .csv',
            'style': 'padding:10px 14px; background:#f8fafc; border:1px solid #cbd5e1; border-radius:10px; width:100%;',
        }),
        help_text="Upload Excel or CSV file with columns: student_id, full_name, section, etc."
    )

    semester = forms.ModelChoiceField(
        queryset=Semester.objects.none(),
        required=False,
        label="Academic Semester (Optional Filter)",
        widget=forms.Select(attrs={
            'style': 'padding:10px 14px; background:#f8fafc; border:1px solid #cbd5e1; border-radius:10px; width:100%;',
        }),
        help_text="Select a semester to filter available course offerings."
    )

    course_offerings = forms.ModelMultipleChoiceField(
        queryset=CourseOffering.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
        label="Target Course Offerings to Enroll Students Into",
        help_text="Check the course offerings all imported students in this file will be enrolled in."
    )

    def __init__(self, organization, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            self.fields['semester'].queryset = Semester.objects.filter(
                organization=organization, is_active=True
            ).select_related('academic_year')
            self.fields['course_offerings'].queryset = CourseOffering.objects.filter(
                course__organization=organization,
                status='ACTIVE'
            ).select_related('course', 'academic_year', 'semester')


class BulkEnrollmentActionForm(forms.Form):
    STRATEGY_CHOICES = [
        ('LECTURE_ONLY', '📚 Lecture only (default — enrolls in course offering without setting a lab group)'),
        ('SPECIFIC_GROUP', '🏷️ Assign to a specific group (available only when exactly 1 course offering is selected)'),
    ]

    semester = forms.ModelChoiceField(
        queryset=Semester.objects.none(),
        required=False,
        label="Target Semester (Optional Filter)",
        widget=forms.Select(attrs={
            'style': 'padding:10px 14px; background:#f8fafc; border:1px solid #cbd5e1; border-radius:10px; width:100%;',
        }),
        help_text="Filter available course offerings by semester."
    )

    course_offerings = forms.ModelMultipleChoiceField(
        queryset=CourseOffering.objects.none(),
        widget=forms.CheckboxSelectMultiple(),
        label="Select Course Offerings",
        required=True,
    )

    strategy = forms.ChoiceField(
        choices=STRATEGY_CHOICES,
        initial='LECTURE_ONLY',
        widget=forms.RadioSelect(),
        label="Group Assignment Mode",
        required=False,
    )

    specific_group = forms.ModelChoiceField(
        queryset=Group.objects.none(),
        required=False,
        label="Specific Group",
        widget=forms.Select(attrs={
            'style': 'padding:10px 14px; background:#f8fafc; border:1px solid #cbd5e1; border-radius:10px; width:100%;',
        }),
        help_text="Select a group (valid only when choosing exactly 1 course offering above)."
    )

    def __init__(self, organization, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        if organization:
            self.fields['semester'].queryset = Semester.objects.filter(
                organization=organization, is_active=True
            ).select_related('academic_year')
            self.fields['course_offerings'].queryset = CourseOffering.objects.filter(
                course__organization=organization, status='ACTIVE'
            ).select_related('course', 'academic_year', 'semester')
            self.fields['specific_group'].queryset = Group.objects.filter(
                course_offering__course__organization=organization, status='ACTIVE'
            ).select_related('course_offering__course')

    def clean(self):
        cleaned_data = super().clean()
        offerings = cleaned_data.get('course_offerings')
        strategy = cleaned_data.get('strategy', 'LECTURE_ONLY')
        specific_group = cleaned_data.get('specific_group')

        if not offerings:
            raise forms.ValidationError("Please select at least one course offering.")

        if strategy == 'SPECIFIC_GROUP' or specific_group:
            if len(offerings) > 1:
                raise forms.ValidationError(
                    "A specific group can only be assigned when enrolling into exactly one course offering. "
                    "For multiple course offerings, choose 'Lecture only'."
                )
            if specific_group and specific_group.course_offering_id != offerings[0].id:
                raise forms.ValidationError(
                    f"Selected group '{specific_group.name}' does not belong to course offering '{offerings[0]}'."
                )

        return cleaned_data

