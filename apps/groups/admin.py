from django.contrib import admin
from apps.accounts.admin import OrgScopedAdminMixin
from .models import Group


@admin.register(Group)
class GroupAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    org_field = 'course_offering__course__organization'
    related_org_fields = {
        'course_offering': 'course__organization',
        'teaching_assistant': 'organization',
    }
    list_display = ['name', 'course_offering', 'teaching_assistant', 'status']
    list_filter = ['status', 'course_offering__academic_year']
    search_fields = ['name', 'course_offering__course__code', 'course_offering__course__name']
    autocomplete_fields = ['course_offering', 'teaching_assistant']
