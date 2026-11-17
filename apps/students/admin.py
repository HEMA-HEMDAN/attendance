"""
Enhanced Students admin with native django-import-export and single-form member creation.
"""

from django.contrib import admin, messages
from django.utils.html import format_html
from django.shortcuts import render, redirect
from django.core.exceptions import ValidationError
from import_export.results import RowResult

from apps.accounts.admin import TenantScopedImportExportAdmin
from apps.organizations.models import Organization
from apps.devices.models import Device
from apps.courses.models import CourseOffering, CourseOfferingStatus
from apps.groups.models import Group
from .models import Student, StudentStatus, StudentEnrollment
from .forms import StudentAdminForm, StudentEnrollmentAdminForm, BulkEnrollmentActionForm
from .resources import StudentResource, StudentEnrollmentResource
from .services.bulk_enrollment import BulkEnrollmentActionService


class StudentEnrollmentInline(admin.TabularInline):
    model = StudentEnrollment
    form = StudentEnrollmentAdminForm
    extra = 1
    autocomplete_fields = ['course_offering']
    verbose_name = 'Course Enrollment'
    verbose_name_plural = 'Course Enrollments'

    class Media:
        js = ('admin/js/schedule_group_filter.js',)


class DeviceInline(admin.TabularInline):
    model = Device
    extra = 0
    readonly_fields = ['device_fingerprint', 'platform', 'device_name', 'status', 'registered_at', 'last_seen_at']
    fields = readonly_fields
    can_delete = False
    show_change_link = False
    verbose_name = 'Registered Device'
    verbose_name_plural = 'Registered Devices'


@admin.register(Student)
class StudentAdmin(TenantScopedImportExportAdmin):
    form = StudentAdminForm
    resource_classes = [StudentResource]
    related_org_fields = {'user': 'organization'}
    list_display = ['student_id', 'get_full_name', 'get_email', 'personal_email', 'department', 'academic_level', 'status_badge']
    list_filter = ['status', 'department', 'academic_level']
    search_fields = ['student_id', 'user__email', 'user__first_name', 'user__last_name', 'personal_email']
    autocomplete_fields = ['user', 'organization']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [StudentEnrollmentInline, DeviceInline]
    actions = ['bulk_enroll_students', 'reset_device_fingerprints', 'deactivate_students', 'activate_students']

    fieldsets = (
        ('Account & Identity', {'fields': ('organization', 'student_id', 'email', 'first_name', 'last_name', 'status')}),
        ('Academic Info', {'fields': ('department', 'academic_level')}),
        ('Contact Info', {'fields': ('phone', 'personal_email')}),
        ('Meta', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    class Media:
        js = ('admin/js/schedule_group_filter.js',)

    def get_form(self, request, obj=None, change=False, **kwargs):
        Form = super().get_form(request, obj, change, **kwargs)
        class RequestBoundForm(Form):
            def __init__(self, *args, **form_kwargs):
                self.request = request
                super().__init__(*args, **form_kwargs)
        return RequestBoundForm

    def save_model(self, request, obj, form, change):
        if not change:
            if not request.user.is_superuser:
                obj.organization = request.user.organization
            elif 'organization' in form.cleaned_data and form.cleaned_data['organization']:
                obj.organization = form.cleaned_data['organization']
        super().save_model(request, obj, form, change)

    def get_full_name(self, obj):
        return obj.user.get_full_name() if obj.user else ''
    get_full_name.short_description = 'Name'

    def get_email(self, obj):
        return obj.user.email if obj.user else ''
    get_email.short_description = 'Email'

    def status_badge(self, obj):
        colors = {
            'ACTIVE': '#10b981',
            'SUSPENDED': '#f59e0b',
            'ARCHIVED': '#64748b',
        }
        color = colors.get(obj.status, '#64748b')
        return format_html(
            '<span style="background:{};color:white;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;">{}</span>',
            color, obj.status
        )
    status_badge.short_description = 'Status'

    def deactivate_students(self, request, queryset):
        count = queryset.update(status=StudentStatus.SUSPENDED)
        self.message_user(request, f'{count} student(s) suspended.')
    deactivate_students.short_description = 'Suspend selected students'

    def activate_students(self, request, queryset):
        count = queryset.update(status=StudentStatus.ACTIVE)
        self.message_user(request, f'{count} student(s) activated.')
    activate_students.short_description = 'Activate selected students'

    def reset_device_fingerprints(self, request, queryset):
        student_users = queryset.values_list('user_id', flat=True)
        count = Device.objects.filter(student__user_id__in=student_users).delete()[0]
        self.message_user(request, f'Reset device registrations for {count} device(s). Students can now pair a new phone.')
    reset_device_fingerprints.short_description = '📱 Reset device fingerprints for selected'

    def bulk_enroll_students(self, request, queryset):
        """Action allowing staff to select students, assign per-offering sections, preview dry-run, and confirm."""
        if not queryset.exists():
            self.message_user(request, "No students selected.", level=messages.WARNING)
            return None

        # Verify permissions
        if not request.user.has_perm('students.add_studentenrollment'):
            self.message_user(request, "You do not have permission to create student enrollments.", level=messages.ERROR)
            return None

        # Resolve target organization
        if request.user.is_superuser:
            org_ids = set(queryset.values_list('organization_id', flat=True))
            if len(org_ids) != 1:
                self.message_user(
                    request,
                    "Error: Selected students belong to different organizations. Please select students from a single organization.",
                    level=messages.ERROR
                )
                return None
            target_org = Organization.objects.get(id=org_ids.pop())
        else:
            target_org = request.user.organization
            if queryset.filter(organization=target_org).count() != queryset.count():
                self.message_user(request, "Selected students must belong to your organization.", level=messages.ERROR)
                return None

        action_step = request.POST.get('action_step')

        # Backward-compatibility: if legacy form submitted with 'apply'
        if 'apply' in request.POST and not action_step:
            action_step = 'confirm'

        # 1. Step: Confirm & Execute
        if action_step == 'confirm':
            offering_ids = request.POST.getlist('course_offerings')
            if not offering_ids:
                self.message_user(request, "Please select at least one course offering.", level=messages.ERROR)
                return redirect(request.get_full_path())

            # Check legacy specific_group parameter
            legacy_group_id = request.POST.get('specific_group')
            legacy_gid = int(legacy_group_id) if legacy_group_id and legacy_group_id.isdigit() else None

            offering_groups = {}
            for oid_str in offering_ids:
                try:
                    oid = int(oid_str)
                except (ValueError, TypeError):
                    continue
                gid_str = request.POST.get(f'group_for_{oid}')
                if gid_str and gid_str.isdigit():
                    offering_groups[oid] = int(gid_str)
                elif legacy_gid is not None:
                    offering_groups[oid] = legacy_gid
                else:
                    offering_groups[oid] = None

            try:
                result = BulkEnrollmentActionService.execute_enrollment(
                    student_queryset=queryset,
                    offering_groups=offering_groups,
                    organization=target_org,
                    dry_run=False
                )
            except ValidationError as err:
                self.message_user(request, f"Enrollment failed: {err}", level=messages.ERROR)
                return redirect(request.get_full_path())

            msg = (
                f"Bulk course assignment complete: {result.created_count} enrollment(s) created, "
                f"{result.already_existing_count} already existed (preserved unchanged). "
                f"{result.rejected_count} invalid selection(s) rejected."
            )
            self.message_user(request, msg, level=messages.SUCCESS)
            return redirect(request.get_full_path())

        # 2. Step: Genuine Dry-Run Preview
        elif action_step == 'preview':
            offering_ids = request.POST.getlist('course_offerings')
            if not offering_ids:
                self.message_user(request, "Please select at least one course offering to preview.", level=messages.ERROR)
            else:
                offering_groups = {}
                for oid_str in offering_ids:
                    try:
                        oid = int(oid_str)
                    except (ValueError, TypeError):
                        continue
                    gid_str = request.POST.get(f'group_for_{oid}')
                    offering_groups[oid] = int(gid_str) if gid_str and gid_str.isdigit() else None

                try:
                    preview_result = BulkEnrollmentActionService.execute_enrollment(
                        student_queryset=queryset,
                        offering_groups=offering_groups,
                        organization=target_org,
                        dry_run=True
                    )

                    offerings_objs = CourseOffering.objects.filter(
                        id__in=offering_groups.keys(),
                        course__organization=target_org,
                        status=CourseOfferingStatus.ACTIVE
                    ).select_related('course', 'academic_year', 'semester').order_by('course__code')

                    preview_offerings = []
                    for off in offerings_objs:
                        gid = offering_groups.get(off.id)
                        group_obj = Group.objects.filter(id=gid, course_offering=off).first() if gid else None
                        preview_offerings.append({
                            'offering': off,
                            'group': group_obj,
                            'group_id': gid,
                            'group_name': group_obj.name if group_obj else 'Lecture only (No group)'
                        })

                    context = {
                        'title': 'Preview Bulk Course Enrollments',
                        'students': queryset,
                        'preview_offerings': preview_offerings,
                        'preview_result': preview_result,
                        'opts': self.model._meta,
                    }
                    return render(request, 'admin/students/bulk_enroll_preview.html', context)
                except ValidationError as err:
                    self.message_user(request, f"Validation error: {err}", level=messages.ERROR)

        # 3. Default: Render Selection Form
        available_offerings = CourseOffering.objects.filter(
            course__organization=target_org,
            status=CourseOfferingStatus.ACTIVE
        ).select_related('course', 'academic_year', 'semester').prefetch_related('groups').order_by('course__code')

        preselected_offering_ids = set(int(x) for x in request.POST.getlist('course_offerings') if x.isdigit())
        for off in available_offerings:
            val = request.POST.get(f'group_for_{off.id}')
            off.selected_group_id = int(val) if val and val.isdigit() else None

        context = {
            'title': 'Bulk Enroll Selected Students in Courses',
            'students': queryset,
            'offerings': available_offerings,
            'preselected_offering_ids': preselected_offering_ids,
            'opts': self.model._meta,
        }
        return render(request, 'admin/students/bulk_enroll.html', context)
    bulk_enroll_students.short_description = '⚡ Bulk Enroll Selected Students in Courses'



@admin.register(StudentEnrollment)
class StudentEnrollmentAdmin(TenantScopedImportExportAdmin):
    form = StudentEnrollmentAdminForm
    resource_classes = [StudentEnrollmentResource]
    org_field = 'student__organization'
    related_org_fields = {
        'student': 'organization',
        'course_offering': 'course__organization',
        'group': 'course_offering__course__organization',
    }
    list_display = ['get_student_id', 'get_student_name', 'get_course_code', 'get_course_name', 'get_group_name', 'created_at']
    list_filter = ['course_offering__academic_year', 'course_offering__semester', 'course_offering', 'group']
    search_fields = ['student__student_id', 'student__user__email', 'student__user__first_name', 'student__user__last_name', 'course_offering__course__code', 'course_offering__course__name']
    autocomplete_fields = ['student', 'course_offering', 'group']

    class Media:
        js = ('admin/js/schedule_group_filter.js',)

    def get_student_id(self, obj):
        return obj.student.student_id
    get_student_id.short_description = 'Student ID'

    def get_student_name(self, obj):
        return obj.student.user.get_full_name()
    get_student_name.short_description = 'Student Name'

    def get_course_code(self, obj):
        return obj.course_offering.course.code
    get_course_code.short_description = 'Course Code'

    def get_course_name(self, obj):
        return obj.course_offering.course.name
    get_course_name.short_description = 'Course Name'

    def get_group_name(self, obj):
        return obj.group.name if obj.group else 'Lecture only'
    get_group_name.short_description = 'Section / Group'
