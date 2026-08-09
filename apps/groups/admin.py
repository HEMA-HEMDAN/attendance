"""
Enhanced Groups admin — show student count, manage members inline.
"""

from django.contrib import admin
from django.utils.html import format_html

from apps.accounts.admin import OrgScopedAdminMixin
from .models import Group


@admin.register(Group)
class GroupAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    list_display = ['name', 'organization', 'status_badge', 'student_count', 'created_at']
    list_filter = ['status', 'organization']
    search_fields = ['name']
    readonly_fields = ['created_at', 'updated_at', 'student_count']

    def status_badge(self, obj):
        color = '#28a745' if obj.status == 'ACTIVE' else '#6c757d'
        return format_html(
            '<span style="background:{};color:white;padding:2px 6px;border-radius:4px;font-size:11px">{}</span>',
            color, obj.status
        )
    status_badge.short_description = 'Status'

    def student_count(self, obj):
        return obj.students.filter(status='ACTIVE').count()
    student_count.short_description = 'Active Students'
