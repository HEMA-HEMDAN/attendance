from django.contrib import admin
from .models import AttendanceLocation

@admin.register(AttendanceLocation)
class AttendanceLocationAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'radius_meters', 'status']
    list_filter = ['status', 'organization']
    search_fields = ['name']
