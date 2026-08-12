"""
Enhanced Courses admin with group assignments.
"""

from django.contrib import admin
from apps.accounts.admin import OrgScopedAdminMixin
from .models import Course


@admin.register(Course)
class CourseAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    list_display = ['name', 'code', 'teacher', 'department', 'level', 'organization', 'status', 'group_list']
    list_filter = ['status', 'organization', 'academic_year', 'semester', 'department', 'level']
    filter_horizontal = ['groups']
    search_fields = ['name', 'code', 'department']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Basic Info', {'fields': ('organization', 'name', 'code', 'teacher', 'status')}),
        ('Academic Structure', {'fields': ('academic_year', 'semester', 'department', 'level')}),
        ('Groups', {'fields': ('groups',)}),
    )

    def group_list(self, obj):
        return ', '.join(obj.groups.values_list('name', flat=True)) or '—'
    group_list.short_description = 'Groups'
