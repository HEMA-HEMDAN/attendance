"""
Enhanced Audit admin — read-only event log with color-coded actions.
"""

from django.contrib import admin
from django.utils.html import format_html
from .models import AuditLog
from apps.accounts.admin import OrgScopedAdminMixin


ACTION_COLORS = {
    'STUDENT_CREATED': '#28a745',
    'STUDENT_UPDATED': '#17a2b8',
    'STUDENT_DISABLED': '#ffc107',
    'STUDENT_IMPORTED': '#28a745',
    'DEVICE_REGISTERED': '#17a2b8',
    'DEVICE_REVOKED': '#dc3545',
    'SESSION_CREATED': '#28a745',
    'SESSION_CLOSED': '#6c757d',
    'ATTENDANCE_ACCEPTED': '#28a745',
    'ATTENDANCE_REJECTED': '#dc3545',
    'BIOMETRIC_FAILED': '#dc3545',
    'LOCATION_FAILED': '#ffc107',
    'LOGIN_SUCCESS': '#28a745',
    'LOGIN_FAILED': '#dc3545',
}


@admin.register(AuditLog)
class AuditLogAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    list_display = ['action_badge', 'actor', 'organization', 'target_type', 'target_id', 'ip_address', 'created_at']
    list_filter = ['action', 'organization']
    search_fields = ['actor__email', 'target_id', 'action']
    readonly_fields = ['organization', 'actor', 'action', 'target_type', 'target_id', 'metadata', 'ip_address', 'created_at']
    ordering = ['-created_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def action_badge(self, obj):
        color = ACTION_COLORS.get(obj.action, '#6c757d')
        return format_html(
            '<span style="background:{};color:white;padding:2px 6px;border-radius:4px;font-size:11px">{}</span>',
            color, obj.action
        )
    action_badge.short_description = 'Action'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(organization=request.user.organization)
