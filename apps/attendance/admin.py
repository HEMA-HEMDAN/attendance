from django.contrib import admin
from .models import SessionOccurrence, AttendanceSession, AttendanceRecord, DeviceChallenge


@admin.register(SessionOccurrence)
class SessionOccurrenceAdmin(admin.ModelAdmin):
    list_display = ['id', 'course_offering', 'group', 'session_type', 'scheduled_date', 'starts_at', 'status']
    list_filter = ['session_type', 'status', 'scheduled_date']
    search_fields = ['course_offering__course__code', 'course_offering__course__name']


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = ['id', 'occurrence', 'organization', 'opened_by', 'status', 'starts_at', 'expires_at']
    list_filter = ['status', 'organization']
    search_fields = ['occurrence__course_offering__course__code']


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ['id', 'session', 'student', 'status', 'verified_at', 'distance_from_location_meters']
    list_filter = ['status', 'verified_at']
    search_fields = ['student__student_id', 'student__user__first_name', 'student__user__last_name']


@admin.register(DeviceChallenge)
class DeviceChallengeAdmin(admin.ModelAdmin):
    list_display = ['id', 'device', 'session', 'is_used', 'expires_at']
    list_filter = ['is_used']
