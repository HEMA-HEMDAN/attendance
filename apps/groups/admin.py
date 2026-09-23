from django.contrib import admin
from .models import Group


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ['name', 'course_offering', 'teaching_assistant', 'status']
    list_filter = ['status', 'course_offering__academic_year']
    search_fields = ['name', 'course_offering__course__code']
