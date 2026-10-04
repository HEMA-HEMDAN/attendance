from django.contrib import admin
from apps.accounts.admin import OrgScopedAdminMixin
from .models import AttendanceLocation

@admin.register(AttendanceLocation)
class AttendanceLocationAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    list_display = ['name', 'organization', 'radius_meters', 'status']
    list_filter = ['status', 'organization']
    search_fields = ['name']
    autocomplete_fields = ['organization']
