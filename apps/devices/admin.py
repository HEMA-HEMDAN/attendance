"""
Enhanced Devices admin with export-only support and revoke action.
"""

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from apps.accounts.admin import TenantScopedImportExportAdmin
from .models import Device
from .resources import DeviceResource


@admin.register(Device)
class DeviceAdmin(TenantScopedImportExportAdmin):
    resource_classes = [DeviceResource]
    import_enabled = False
    export_enabled = True

    related_org_fields = {'student': 'organization'}
    list_display = [
        'student', 'platform', 'device_name',
        'status_badge', 'registered_at', 'last_seen_at', 'biometric_invalidated',
    ]
    list_filter = ['status', 'platform', 'organization', 'biometric_invalidated']
    search_fields = ['student__student_id', 'student__user__email', 'device_name']
    autocomplete_fields = ['student', 'organization']
    readonly_fields = [
        'student', 'organization', 'device_fingerprint', 'platform',
        'device_name', 'os_version', 'registered_at', 'revoked_at',
        'last_seen_at', 'biometric_invalidated',
    ]
    actions = ['revoke_devices', 'mark_biometric_invalidated']

    def status_badge(self, obj):
        color = '#28a745' if obj.status == 'ACTIVE' else '#dc3545'
        return format_html(
            '<span style="background:{};color:white;padding:2px 8px;border-radius:4px;font-size:11px">{}</span>',
            color, obj.status
        )
    status_badge.short_description = 'Status'

    def revoke_devices(self, request, queryset):
        count = queryset.filter(status='ACTIVE').update(
            status='REVOKED', revoked_at=timezone.now()
        )
        self.message_user(request, f'{count} device(s) revoked.')
    revoke_devices.short_description = 'Revoke selected devices'

    def mark_biometric_invalidated(self, request, queryset):
        count = queryset.update(biometric_invalidated=True)
        self.message_user(request, f'{count} device(s) marked as biometric-invalidated.')
    mark_biometric_invalidated.short_description = 'Mark biometric as invalidated'
