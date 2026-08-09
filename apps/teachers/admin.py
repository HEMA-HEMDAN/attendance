from django.contrib import admin
from .models import Teacher

@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ['user', 'organization', 'created_at']
    list_filter = ['organization']
    search_fields = ['user__email', 'user__first_name']
