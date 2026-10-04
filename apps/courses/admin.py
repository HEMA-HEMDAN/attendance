from django.contrib import admin
from apps.accounts.admin import OrgScopedAdminMixin
from .models import AcademicYear, Semester, Course, CourseOffering, Schedule, ScheduleException


@admin.register(AcademicYear)
class AcademicYearAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    list_display = ['name', 'organization', 'start_date', 'end_date', 'is_active']
    list_filter = ['organization', 'is_active']
    search_fields = ['name']
    autocomplete_fields = ['organization']


@admin.register(Semester)
class SemesterAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    list_display = ['name', 'academic_year', 'organization', 'start_date', 'end_date', 'is_active']
    list_filter = ['academic_year', 'is_active']
    search_fields = ['name']
    autocomplete_fields = ['academic_year', 'organization']


@admin.register(Course)
class CourseAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    list_display = ['code', 'name', 'department', 'organization']
    list_filter = ['organization', 'department']
    search_fields = ['code', 'name']
    autocomplete_fields = ['organization']


class ScheduleInline(admin.TabularInline):
    model = Schedule
    extra = 1
    autocomplete_fields = ['group', 'location']
    verbose_name = 'Course Schedule'
    verbose_name_plural = 'Course Schedules'


@admin.register(CourseOffering)
class CourseOfferingAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    org_field = 'course__organization'
    related_org_fields = {
        'course': 'organization',
        'academic_year': 'organization',
        'semester': 'organization',
        'doctor': 'organization',
    }
    list_display = ['course', 'academic_year', 'semester', 'doctor', 'status']
    list_filter = ['academic_year', 'semester', 'status']
    search_fields = ['course__code', 'course__name', 'doctor__user__first_name', 'doctor__user__last_name']
    autocomplete_fields = ['course', 'academic_year', 'semester', 'doctor']
    inlines = [ScheduleInline]


@admin.register(Schedule)
class ScheduleAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    org_field = 'course_offering__course__organization'
    related_org_fields = {
        'course_offering': 'course__organization',
        'group': 'course_offering__course__organization',
        'location': 'organization',
        'doctor': 'organization',
        'teaching_assistant': 'organization',
    }
    list_display = ['course_offering', 'group', 'doctor', 'teaching_assistant', 'session_type', 'day_of_week', 'start_time', 'end_time', 'is_active']
    list_filter = ['session_type', 'day_of_week', 'is_active', 'doctor', 'teaching_assistant']
    search_fields = [
        'course_offering__course__code',
        'course_offering__course__name',
        'group__name',
        'doctor__user__first_name',
        'doctor__user__last_name',
        'teaching_assistant__user__first_name',
        'teaching_assistant__user__last_name',
    ]
    autocomplete_fields = ['course_offering', 'group', 'location', 'doctor', 'teaching_assistant']


@admin.register(ScheduleException)
class ScheduleExceptionAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    org_field = 'schedule__course_offering__course__organization'
    related_org_fields = {'schedule': 'course_offering__course__organization'}
    list_display = ['schedule', 'date', 'exception_type', 'reason']
    list_filter = ['exception_type', 'date']
    search_fields = ['schedule__course_offering__course__code', 'reason']
    autocomplete_fields = ['schedule']
