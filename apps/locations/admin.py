from django.contrib import admin
from apps.accounts.admin import TenantScopedImportExportAdmin
from .models import AttendanceLocation
from .resources import AttendanceLocationResource


@admin.register(AttendanceLocation)
class AttendanceLocationAdmin(TenantScopedImportExportAdmin):
    resource_classes = [AttendanceLocationResource]
    list_display = ['name', 'organization', 'radius_meters', 'status']
    list_filter = ['status', 'organization']
    search_fields = ['name']
    autocomplete_fields = ['organization']
