from django.contrib import admin
from .models import AcademicYear, Semester, Course, CourseOffering, Schedule, ScheduleException


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'start_date', 'end_date', 'is_active']
    list_filter = ['organization', 'is_active']


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ['name', 'academic_year', 'organization', 'start_date', 'end_date', 'is_active']
    list_filter = ['academic_year', 'is_active']


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'department', 'organization']
    list_filter = ['organization', 'department']
    search_fields = ['code', 'name']


@admin.register(CourseOffering)
class CourseOfferingAdmin(admin.ModelAdmin):
    list_display = ['course', 'academic_year', 'semester', 'doctor', 'status']
    list_filter = ['academic_year', 'semester', 'status']
    search_fields = ['course__code', 'course__name']


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ['course_offering', 'group', 'session_type', 'day_of_week', 'start_time', 'end_time', 'is_active']
    list_filter = ['session_type', 'day_of_week', 'is_active']


@admin.register(ScheduleException)
class ScheduleExceptionAdmin(admin.ModelAdmin):
    list_display = ['schedule', 'date', 'exception_type', 'reason']
    list_filter = ['exception_type', 'date']
