from django.contrib import admin
from apps.accounts.admin import OrgScopedAdminMixin, TenantScopedImportExportAdmin
from .models import SessionOccurrence, AttendanceSession, AttendanceRecord, DeviceChallenge
from .resources import AttendanceSessionResource, AttendanceRecordResource


@admin.register(SessionOccurrence)
class SessionOccurrenceAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    org_field = 'course_offering__course__organization'

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    list_display = ['id', 'course_offering', 'group', 'session_type', 'occurrence_type', 'scheduled_date', 'status']
    list_filter = ['occurrence_type', 'session_type', 'status', 'scheduled_date']
    search_fields = ['course_offering__course__code', 'course_offering__course__name']
    autocomplete_fields = ['course_offering', 'group']


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(TenantScopedImportExportAdmin):
    resource_classes = [AttendanceSessionResource]
    import_enabled = False
    export_enabled = True

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    list_display = ['id', 'occurrence', 'organization', 'opened_by', 'status', 'latitude', 'longitude', 'location_accuracy_meters', 'radius_meters']
    list_filter = ['status', 'organization']
    search_fields = ['occurrence__course_offering__course__code', 'occurrence__course_offering__course__name', 'opened_by__email']
    autocomplete_fields = ['occurrence', 'opened_by', 'organization']
    readonly_fields = ['opened_by', 'latitude', 'longitude', 'location_accuracy_meters', 'location_captured_at', 'radius_meters']


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(TenantScopedImportExportAdmin):
    resource_classes = [AttendanceRecordResource]
    import_enabled = False
    export_enabled = True
    org_field = 'session__organization'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    list_display = ['id', 'session', 'get_student_id', 'get_student_name', 'status', 'verified_at', 'distance_from_location_meters']
    list_filter = ['status', 'verified_at', 'mock_location_detected']
    search_fields = ['student__student_id', 'student__user__first_name', 'student__user__last_name']
    autocomplete_fields = ['session', 'student']

    def get_student_id(self, obj):
        return obj.student.student_id
    get_student_id.short_description = 'Student ID'

    def get_student_name(self, obj):
        return obj.student.user.get_full_name()
    get_student_name.short_description = 'Student Name'


@admin.register(DeviceChallenge)
class DeviceChallengeAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    org_field = 'session__organization'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    list_display = ['id', 'device', 'session', 'is_used', 'expires_at']
    list_filter = ['is_used']
    search_fields = ['device__device_name', 'session__id']
    autocomplete_fields = ['device', 'session']
