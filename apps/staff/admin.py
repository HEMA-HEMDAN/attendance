from django.contrib import admin, messages
from django.shortcuts import render, redirect
from django.core.exceptions import ValidationError
from apps.accounts.admin import TenantScopedImportExportAdmin
from .models import Doctor, TeachingAssistant
from .forms import DoctorAdminForm, TeachingAssistantAdminForm, DoctorScheduleInlineForm, TAScheduleInlineForm
from .resources import DoctorResource, TeachingAssistantResource
from apps.courses.models import CourseOffering, Schedule, CourseOfferingStatus, SessionType
from apps.groups.models import Group, GroupStatus
from apps.courses.forms import ScheduleAdminForm
from apps.locations.models import AttendanceLocation
from apps.staff.services.staff_assignment import StaffAssignmentService


class CourseOfferingInline(admin.TabularInline):
    model = CourseOffering
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ['course', 'academic_year', 'semester', 'status']
    readonly_fields = ['course', 'academic_year', 'semester', 'status']
    verbose_name = 'Taught Course Offering'
    verbose_name_plural = 'Taught Course Offerings'

    def has_add_permission(self, request, obj=None):
        return False


class DoctorScheduleInline(admin.TabularInline):
    model = Schedule
    form = DoctorScheduleInlineForm
    fk_name = 'doctor'
    extra = 0
    show_change_link = True
    fields = ['course_offering', 'room_label', 'day_of_week', 'start_time', 'end_time', 'effective_from', 'effective_until', 'is_active']
    verbose_name = 'Doctor Lecture Schedule'
    verbose_name_plural = 'Doctor Lecture Schedules'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(session_type=SessionType.LECTURE)

    def get_formset(self, request, obj=None, **kwargs):
        request._editing_doctor = obj
        return super().get_formset(request, obj, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        doctor = getattr(request, '_editing_doctor', None)
        if db_field.name == 'course_offering':
            if doctor:
                kwargs['queryset'] = CourseOffering.objects.filter(doctor=doctor)
            else:
                kwargs['queryset'] = CourseOffering.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class AssignedGroupInline(admin.TabularInline):
    model = Group
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ['course_offering', 'name', 'status']
    readonly_fields = ['course_offering', 'name', 'status']
    verbose_name = 'Assigned Lab Section / Group'
    verbose_name_plural = 'Assigned Lab Sections / Groups'

    def has_add_permission(self, request, obj=None):
        return False


class TAScheduleInline(admin.TabularInline):
    model = Schedule
    form = TAScheduleInlineForm
    fk_name = 'teaching_assistant'
    extra = 0
    show_change_link = True
    fields = ['course_offering', 'group', 'day_of_week', 'start_time', 'end_time', 'is_active']
    verbose_name = 'TA Lab Schedule'
    verbose_name_plural = 'TA Lab Schedules'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(session_type=SessionType.LAB)

    def get_formset(self, request, obj=None, **kwargs):
        request._editing_ta = obj
        return super().get_formset(request, obj, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        ta = getattr(request, '_editing_ta', None)
        if db_field.name == 'group':
            if ta:
                kwargs['queryset'] = Group.objects.filter(teaching_assistant=ta)
            else:
                kwargs['queryset'] = Group.objects.none()
        elif db_field.name == 'course_offering':
            if ta:
                kwargs['queryset'] = CourseOffering.objects.filter(groups__teaching_assistant=ta).distinct()
            else:
                kwargs['queryset'] = CourseOffering.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Doctor)
class DoctorAdmin(TenantScopedImportExportAdmin):
    change_form_template = 'admin/staff/doctor/change_form.html'
    form = DoctorAdminForm
    resource_classes = [DoctorResource]
    related_org_fields = {'user': 'organization'}
    list_display = ['title', 'get_full_name', 'email', 'department']
    list_filter = ['department']
    search_fields = ['user__first_name', 'user__last_name', 'user__email', 'department']
    autocomplete_fields = ['user', 'organization']
    inlines = [CourseOfferingInline, DoctorScheduleInline]
    actions = ['assign_courses_to_doctor']
    fieldsets = (
        ('Doctor Info', {'fields': ('organization', 'email', 'first_name', 'last_name', 'title', 'department')}),
    )

    @admin.action(description='⚡ Assign / Reassign Course Offerings to Doctor')
    def assign_courses_to_doctor(self, request, queryset):
        if not queryset.exists():
            self.message_user(request, "No doctor selected.", level=messages.WARNING)
            return None

        if queryset.count() > 1:
            self.message_user(
                request,
                "Please select exactly one doctor at a time to assign to course offerings.",
                level=messages.WARNING
            )
            return None

        doctor = queryset.first()

        if request.user.is_superuser:
            target_org = doctor.organization
        else:
            target_org = request.user.organization
            if doctor.organization_id != target_org.id:
                self.message_user(request, "Selected doctor must belong to your organization.", level=messages.ERROR)
                return None

        action_step = request.POST.get('action_step')

        # 1. Step: Confirm & Execute
        if action_step == 'confirm':
            offering_ids = [int(x) for x in request.POST.getlist('course_offerings') if x.isdigit()]
            if not offering_ids:
                self.message_user(request, "Please select at least one course offering.", level=messages.ERROR)
                return redirect(request.get_full_path())

            try:
                result = StaffAssignmentService.assign_doctor_to_offerings(
                    doctor=doctor,
                    course_offering_ids=offering_ids,
                    organization=target_org,
                    dry_run=False
                )
            except ValidationError as err:
                self.message_user(request, f"Assignment failed: {err}", level=messages.ERROR)
                return redirect(request.get_full_path())

            msg = (
                f"Course assignment complete for {doctor.title} {doctor.user.get_full_name()}: "
                f"{result.newly_assigned_count} newly assigned, "
                f"{result.reassigned_count} reassigned (previous doctors replaced), "
                f"{result.unchanged_count} unchanged."
            )
            self.message_user(request, msg, level=messages.SUCCESS)
            return redirect(request.get_full_path())

        # 2. Step: Genuine Dry-Run Preview
        elif action_step == 'preview':
            offering_ids = [int(x) for x in request.POST.getlist('course_offerings') if x.isdigit()]
            if not offering_ids:
                self.message_user(request, "Please select at least one course offering to preview.", level=messages.ERROR)
            else:
                try:
                    preview_result = StaffAssignmentService.assign_doctor_to_offerings(
                        doctor=doctor,
                        course_offering_ids=offering_ids,
                        organization=target_org,
                        dry_run=True
                    )
                    context = {
                        'title': f'Preview Course Assignments — {doctor}',
                        'doctor': doctor,
                        'offering_ids': offering_ids,
                        'preview_result': preview_result,
                        'opts': self.model._meta,
                    }
                    return render(request, 'admin/staff/assign_doctor_courses_preview.html', context)
                except ValidationError as err:
                    self.message_user(request, f"Validation error: {err}", level=messages.ERROR)

        # 3. Default: Render Selection Form
        available_offerings = CourseOffering.objects.filter(
            course__organization=target_org,
            status=CourseOfferingStatus.ACTIVE
        ).select_related('course', 'academic_year', 'semester', 'doctor', 'doctor__user').order_by('course__code')

        preselected_offering_ids = set(int(x) for x in request.POST.getlist('course_offerings') if x.isdigit())

        context = {
            'title': f'Assign Courses — {doctor}',
            'doctor': doctor,
            'offerings': available_offerings,
            'preselected_offering_ids': preselected_offering_ids,
            'opts': self.model._meta,
        }
        return render(request, 'admin/staff/assign_doctor_courses.html', context)

    def get_urls(self):
        urls = super().get_urls()
        from django.urls import path
        custom_urls = [
            path('<int:object_id>/assign-courses/', self.admin_site.admin_view(self.assign_courses_single_view), name='staff_doctor_assign_courses'),
        ]
        return custom_urls + urls

    def assign_courses_single_view(self, request, object_id):
        doctor = self.get_object(request, str(object_id))
        if not doctor:
            self.message_user(request, "Doctor not found.", level=messages.ERROR)
            return redirect('admin:staff_doctor_changelist')
        return self.assign_courses_to_doctor(request, Doctor.objects.filter(pk=doctor.pk))

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

    def email(self, obj):
        return obj.user.email if obj.user else ''


@admin.register(TeachingAssistant)
class TeachingAssistantAdmin(TenantScopedImportExportAdmin):
    change_form_template = 'admin/staff/teachingassistant/change_form.html'
    form = TeachingAssistantAdminForm
    resource_classes = [TeachingAssistantResource]
    related_org_fields = {'user': 'organization'}
    list_display = ['get_full_name', 'email', 'department']
    list_filter = ['department']
    search_fields = ['user__first_name', 'user__last_name', 'user__email', 'department']
    autocomplete_fields = ['user', 'organization']
    inlines = [AssignedGroupInline, TAScheduleInline]
    actions = ['assign_groups_to_ta']
    fieldsets = (
        ('Teaching Assistant Info', {'fields': ('organization', 'email', 'first_name', 'last_name', 'department')}),
    )

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        ta = self.get_object(request, object_id)
        if ta:
            import json
            groups_qs = Group.objects.filter(
                course_offering__course__organization=ta.organization,
                status=GroupStatus.ACTIVE
            ).values('id', 'name', 'course_offering_id', 'teaching_assistant_id')
            offering_groups_map = {}
            for g in groups_qs:
                off_id = str(g['course_offering_id'])
                if off_id not in offering_groups_map:
                    offering_groups_map[off_id] = []
                offering_groups_map[off_id].append({
                    'id': g['id'],
                    'name': g['name'],
                    'assigned_to_ta': (g['teaching_assistant_id'] == ta.id)
                })
            extra_context['offering_groups_json'] = json.dumps(offering_groups_map)
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        from django.urls import path
        custom_urls = [
            path('<int:object_id>/assign-groups/', self.admin_site.admin_view(self.assign_groups_single_view), name='staff_teachingassistant_assign_groups'),
        ]
        return custom_urls + urls

    def assign_groups_single_view(self, request, object_id):
        ta = self.get_object(request, str(object_id))
        if not ta:
            self.message_user(request, "Teaching Assistant not found.", level=messages.ERROR)
            return redirect('admin:staff_teachingassistant_changelist')
        return self.assign_groups_to_ta(request, TeachingAssistant.objects.filter(pk=ta.pk))

    @admin.action(description='⚡ Assign / Reassign Sections / Groups to TA')
    def assign_groups_to_ta(self, request, queryset):
        if not queryset.exists():
            self.message_user(request, "No teaching assistant selected.", level=messages.WARNING)
            return None

        if queryset.count() > 1:
            self.message_user(
                request,
                "Please select exactly one teaching assistant at a time to assign to groups.",
                level=messages.WARNING
            )
            return None

        ta = queryset.first()

        if request.user.is_superuser:
            target_org = ta.organization
        else:
            target_org = request.user.organization
            if ta.organization_id != target_org.id:
                self.message_user(request, "Selected TA must belong to your organization.", level=messages.ERROR)
                return None

        action_step = request.POST.get('action_step')

        # 1. Step: Confirm & Execute
        if action_step == 'confirm':
            group_ids = [int(x) for x in request.POST.getlist('groups') if x.isdigit()]
            if not group_ids:
                self.message_user(request, "Please select at least one group.", level=messages.ERROR)
                return redirect(request.get_full_path())

            try:
                result = StaffAssignmentService.assign_ta_to_groups(
                    ta=ta,
                    group_ids=group_ids,
                    organization=target_org,
                    dry_run=False
                )
            except ValidationError as err:
                self.message_user(request, f"Assignment failed: {err}", level=messages.ERROR)
                return redirect(request.get_full_path())

            msg = (
                f"Group assignment complete for TA {ta.user.get_full_name()}: "
                f"{result.newly_assigned_count} newly assigned, "
                f"{result.reassigned_count} reassigned (previous TAs replaced), "
                f"{result.unchanged_count} unchanged."
            )
            self.message_user(request, msg, level=messages.SUCCESS)
            return redirect(request.get_full_path())

        # 2. Step: Genuine Dry-Run Preview
        elif action_step == 'preview':
            group_ids = [int(x) for x in request.POST.getlist('groups') if x.isdigit()]
            if not group_ids:
                self.message_user(request, "Please select at least one group to preview.", level=messages.ERROR)
            else:
                try:
                    preview_result = StaffAssignmentService.assign_ta_to_groups(
                        ta=ta,
                        group_ids=group_ids,
                        organization=target_org,
                        dry_run=True
                    )
                    context = {
                        'title': f'Preview Group Assignments — TA {ta.user.get_full_name()}',
                        'ta': ta,
                        'group_ids': group_ids,
                        'preview_result': preview_result,
                        'opts': self.model._meta,
                    }
                    return render(request, 'admin/staff/assign_ta_groups_preview.html', context)
                except ValidationError as err:
                    self.message_user(request, f"Validation error: {err}", level=messages.ERROR)

        # 3. Default: Render Selection Form
        available_offerings = CourseOffering.objects.filter(
            course__organization=target_org,
            status=CourseOfferingStatus.ACTIVE
        ).select_related('course', 'academic_year', 'semester').prefetch_related(
            'groups', 'groups__teaching_assistant', 'groups__teaching_assistant__user'
        ).order_by('course__code')

        preselected_group_ids = set(int(x) for x in request.POST.getlist('groups') if x.isdigit())

        context = {
            'title': f'Allocate Existing Groups — TA {ta.user.get_full_name()}',
            'ta': ta,
            'offerings': available_offerings,
            'preselected_group_ids': preselected_group_ids,
            'opts': self.model._meta,
        }
        return render(request, 'admin/staff/assign_ta_groups.html', context)

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

    def email(self, obj):
        return obj.user.email if obj.user else ''
