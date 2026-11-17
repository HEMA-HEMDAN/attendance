from django.contrib import admin
from django.shortcuts import render
from django.http import HttpResponseRedirect
from apps.accounts.admin import TenantScopedImportExportAdmin
from .models import Group
from .resources import GroupResource
from apps.courses.models import Schedule


class GroupScheduleInline(admin.TabularInline):
    model = Schedule
    extra = 1
    autocomplete_fields = ['course_offering', 'location']
    verbose_name = 'Group Schedule'
    verbose_name_plural = 'Group Schedules'


@admin.register(Group)
class GroupAdmin(TenantScopedImportExportAdmin):
    resource_classes = [GroupResource]
    org_field = 'course_offering__course__organization'
    related_org_fields = {
        'course_offering': 'course__organization',
        'teaching_assistant': 'organization',
    }
    list_display = ['name', 'course_offering', 'teaching_assistant', 'status']
    list_editable = ['teaching_assistant']
    list_filter = ['status', 'course_offering__academic_year']
    search_fields = ['name', 'course_offering__course__code', 'course_offering__course__name']
    autocomplete_fields = ['course_offering', 'teaching_assistant']
    inlines = [GroupScheduleInline]
    actions = ['reassign_ta']

    @admin.action(description='⚡ Assign / Reassign Selected Groups to a TA')
    def reassign_ta(self, request, queryset):
        from apps.staff.models import TeachingAssistant
        from apps.staff.services.staff_assignment import StaffAssignmentService
        from django.contrib import messages
        from django.core.exceptions import ValidationError

        if not queryset.exists():
            self.message_user(request, "No groups selected.", level=messages.WARNING)
            return None

        first_group = queryset.select_related('course_offering__course__organization').first()
        target_org = first_group.course_offering.course.organization if first_group else None

        if not request.user.is_superuser:
            if not target_org or target_org.id != request.user.organization_id:
                self.message_user(request, "Selected groups must belong to your organization.", level=messages.ERROR)
                return None

        for g in queryset:
            if g.course_offering.course.organization_id != target_org.id:
                self.message_user(request, "All selected groups must belong to the same organization.", level=messages.ERROR)
                return None

        action_step = request.POST.get('action_step')
        new_ta_id = request.POST.get('new_ta')

        if action_step == 'confirm' and new_ta_id and new_ta_id.isdigit():
            ta = TeachingAssistant.objects.filter(pk=int(new_ta_id), organization=target_org).first()
            if not ta:
                self.message_user(request, "Selected Teaching Assistant not found in target organization.", level=messages.ERROR)
                return HttpResponseRedirect(request.get_full_path())

            try:
                result = StaffAssignmentService.assign_ta_to_groups(
                    ta=ta,
                    group_ids=list(queryset.values_list('id', flat=True)),
                    organization=target_org,
                    dry_run=False
                )
                msg = (
                    f"Successfully assigned {result.total_items} groups to TA {ta.user.get_full_name()}: "
                    f"{result.newly_assigned_count} newly assigned, "
                    f"{result.reassigned_count} reassigned (previous TAs replaced), "
                    f"{result.unchanged_count} unchanged."
                )
                self.message_user(request, msg, level=messages.SUCCESS)
                return HttpResponseRedirect(request.get_full_path())
            except ValidationError as err:
                self.message_user(request, f"Assignment failed: {err}", level=messages.ERROR)
                return HttpResponseRedirect(request.get_full_path())

        elif action_step == 'preview' and new_ta_id and new_ta_id.isdigit():
            ta = TeachingAssistant.objects.filter(pk=int(new_ta_id), organization=target_org).first()
            if not ta:
                self.message_user(request, "Selected Teaching Assistant not found in target organization.", level=messages.ERROR)
            else:
                try:
                    preview_result = StaffAssignmentService.assign_ta_to_groups(
                        ta=ta,
                        group_ids=list(queryset.values_list('id', flat=True)),
                        organization=target_org,
                        dry_run=True
                    )
                    context = {
                        'title': f'Review Reassignment of {queryset.count()} Groups',
                        'groups': queryset.select_related('course_offering__course', 'teaching_assistant__user'),
                        'target_ta': ta,
                        'preview_result': preview_result,
                        'action_checkbox_name': admin.helpers.ACTION_CHECKBOX_NAME,
                        'opts': self.model._meta,
                    }
                    return render(request, 'admin/groups/reassign_ta_preview.html', context)
                except ValidationError as err:
                    self.message_user(request, f"Validation error: {err}", level=messages.ERROR)

        tas = TeachingAssistant.objects.filter(organization=target_org).select_related('user').order_by('user__first_name')
        context = {
            'title': f'Assign / Reassign {queryset.count()} Groups to a TA',
            'groups': queryset.select_related('course_offering__course', 'teaching_assistant__user'),
            'tas': tas,
            'selected_ta_id': int(new_ta_id) if new_ta_id and new_ta_id.isdigit() else None,
            'action_checkbox_name': admin.helpers.ACTION_CHECKBOX_NAME,
            'opts': self.model._meta,
        }
        return render(request, 'admin/groups/reassign_ta.html', context)
