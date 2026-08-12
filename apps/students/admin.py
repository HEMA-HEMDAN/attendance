"""
Enhanced Students admin with CSV import action and inline device view.
"""

import csv
from django.contrib import admin, messages
from django.urls import path
from django.shortcuts import render, redirect
from django.utils.html import format_html
from django.http import HttpResponse

from apps.accounts.admin import OrgScopedAdminMixin
from apps.devices.models import Device
from .models import Student, StudentStatus


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
class StudentAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    list_display = ['student_id', 'get_full_name', 'get_email', 'personal_email', 'department', 'academic_level', 'group', 'organization', 'status_badge']
    list_filter = ['status', 'organization', 'group', 'department', 'academic_level']
    search_fields = ['student_id', 'user__email', 'user__first_name', 'user__last_name', 'personal_email']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [DeviceInline]
    actions = ['deactivate_students', 'activate_students', 'export_csv']

    fieldsets = (
        ('Account', {'fields': ('user', 'organization', 'status')}),
        ('Academic Info', {'fields': ('student_id', 'group', 'department', 'academic_level')}),
        ('Contact Info', {'fields': ('phone', 'personal_email')}),
        ('Meta', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    def get_full_name(self, obj):
        return obj.user.get_full_name()
    get_full_name.short_description = 'Name'

    def get_email(self, obj):
        return obj.user.email
    get_email.short_description = 'Email'

    def status_badge(self, obj):
        colors = {
            'ACTIVE': '#28a745',
            'SUSPENDED': '#ffc107',
            'ARCHIVED': '#6c757d',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background:{};color:white;padding:2px 8px;border-radius:4px;font-size:11px">{}</span>',
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

    def export_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="students.csv"'
        writer = csv.writer(response)
        writer.writerow(['student_id', 'first_name', 'last_name', 'email', 'group', 'status'])
        for s in queryset.select_related('user', 'group'):
            writer.writerow([
                s.student_id, s.user.first_name, s.user.last_name,
                s.user.email, s.group.name if s.group else '', s.status
            ])
        return response
    export_csv.short_description = 'Export selected to CSV'

    # ── CSV Import ───────────────────────────────────────────────────────
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('import-csv/', self.admin_site.admin_view(self.csv_import_view), name='student-import-csv'),
        ]
        return custom + urls

    def csv_import_view(self, request):
        """Two-step CSV import: upload → preview → confirm → import."""
        from apps.students.serializers import CSVImportSerializer

        if request.method == 'POST' and 'confirm' in request.POST:
            # Step 2 — actually import
            serializer = CSVImportSerializer(data=request.FILES)
            if serializer.is_valid():
                valid, invalid, dupes = serializer.parse_and_validate(request.user.organization)
                created = serializer.import_rows(valid, request.user.organization)
                messages.success(request, f'Imported {len(created)} students. Skipped {len(dupes)} duplicates.')
            return redirect('..')

        elif request.method == 'POST' and request.FILES.get('file'):
            # Step 1 — preview
            class FakeRequest:
                user = request.user
                data = {}
                FILES = request.FILES
            serializer = CSVImportSerializer(data={'file': request.FILES['file']})
            if serializer.is_valid():
                valid, invalid, dupes = serializer.parse_and_validate(request.user.organization)
                context = {
                    'title': 'Preview CSV Import',
                    'valid': valid,
                    'invalid': invalid,
                    'dupes': dupes,
                    'file': request.FILES['file'],
                    'opts': self.model._meta,
                }
                return render(request, 'admin/students/csv_preview.html', context)
            else:
                messages.error(request, str(serializer.errors))

        context = {
            'title': 'Import Students from CSV',
            'opts': self.model._meta,
        }
        return render(request, 'admin/students/csv_upload.html', context)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['import_url'] = 'import-csv/'
        return super().changelist_view(request, extra_context=extra_context)
