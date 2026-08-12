"""
Enhanced Attendance admin — sessions, records, live monitoring indicators.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone

from apps.accounts.admin import OrgScopedAdminMixin
from .models import AttendanceSession, AttendanceRecord, DeviceChallenge, SessionStatus


class AttendanceRecordInline(admin.TabularInline):
    model = AttendanceRecord
    extra = 0
    readonly_fields = [
        'student', 'status', 'verified_at',
        'distance_from_location_meters', 'location_accuracy_meters',
        'mock_location_detected', 'device_challenge_verified',
    ]
    fields = readonly_fields
    can_delete = False
    ordering = ['verified_at']


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    list_display = [
        'id', 'course', 'group', 'teacher', 'session_type',
        'status_badge', 'starts_at', 'expires_at',
        'present_count', 'late_count', 'total_enrolled',
    ]
    list_filter = ['status', 'organization', 'course', 'session_type']
    search_fields = ['course__name', 'group__name', 'teacher__user__email']
    readonly_fields = [
        'status', 'starts_at', 'expires_at', 'closed_at',
        'created_at', 'present_count', 'late_count', 'total_enrolled',
    ]
    inlines = [AttendanceRecordInline]
    actions = ['close_sessions']

    fieldsets = (
        ('Session', {'fields': ('organization', 'course', 'group', 'teacher', 'session_type')}),
        ('Location (Dynamic)', {'fields': ('latitude', 'longitude', 'radius_meters')}),
        ('Status & Timing', {'fields': ('status', 'starts_at', 'expires_at', 'closed_at', 'duration_minutes')}),
        ('Policy', {'fields': (
            'biometric_required', 'location_required',
            'max_location_accuracy_meters', 'late_after_minutes',
        )}),
        ('Stats', {'fields': ('present_count', 'late_count', 'total_enrolled')}),
    )

    def status_badge(self, obj):
        colors = {
            'ACTIVE': '#28a745',
            'CLOSED': '#6c757d',
            'EXPIRED': '#dc3545',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background:{};color:white;padding:2px 8px;border-radius:4px;font-size:11px">{}</span>',
            color, obj.status
        )
    status_badge.short_description = 'Status'

    def present_count(self, obj):
        return obj.records.filter(status='PRESENT').count()
    present_count.short_description = 'Present'

    def late_count(self, obj):
        return obj.records.filter(status='LATE').count()
    late_count.short_description = 'Late'

    def total_enrolled(self, obj):
        from apps.students.models import Student
        if obj.group:
            return Student.objects.filter(enrollments__course=obj.course, enrollments__group=obj.group, status='ACTIVE').distinct().count()
        return Student.objects.filter(enrollments__course=obj.course, status='ACTIVE').distinct().count()
    total_enrolled.short_description = 'Enrolled'

    def close_sessions(self, request, queryset):
        updated = queryset.filter(status=SessionStatus.ACTIVE).update(
            status=SessionStatus.CLOSED,
            closed_at=timezone.now(),
        )
        self.message_user(request, f'{updated} session(s) closed.')
    close_sessions.short_description = 'Close selected active sessions'


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    org_field = 'session__organization'

    list_display = [
        'student', 'session', 'status_badge',
        'verified_at', 'distance_from_location_meters',
        'mock_location_detected', 'device_challenge_verified',
    ]
    list_filter = ['status', 'mock_location_detected', 'device_challenge_verified']
    search_fields = ['student__student_id', 'student__user__email']
    readonly_fields = [
        'session', 'student', 'device', 'status', 'verified_at',
        'submitted_latitude', 'submitted_longitude',
        'location_accuracy_meters', 'distance_from_location_meters',
        'mock_location_detected', 'device_challenge_verified', 'created_at',
    ]

    def get_queryset(self, request):
        qs = super(admin.ModelAdmin, self).get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(session__organization=request.user.organization)

    def status_badge(self, obj):
        colors = {'PRESENT': '#28a745', 'LATE': '#ffc107', 'EXCUSED': '#17a2b8'}
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background:{};color:white;padding:2px 8px;border-radius:4px;font-size:11px">{}</span>',
            color, obj.status
        )
    status_badge.short_description = 'Status'


@admin.register(DeviceChallenge)
class DeviceChallengeAdmin(admin.ModelAdmin):
    list_display = ['device', 'session', 'is_used', 'created_at', 'expires_at']
    list_filter = ['is_used']
    readonly_fields = ['challenge_token', 'created_at', 'expires_at', 'is_used']
