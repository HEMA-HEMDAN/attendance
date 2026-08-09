"""
Custom Django Admin site configuration.
"""

from django.contrib.admin import AdminSite


class BioAttendanceAdminSite(AdminSite):
    site_header = '🎓 Bio Attendance Admin'
    site_title = 'Bio Attendance'
    index_title = 'Organization Management'
    site_url = None  # Remove "View Site" link from admin


# Override default admin site
from django.contrib import admin
admin.site.site_header = '🎓 Bio Attendance Admin'
admin.site.site_title = 'Bio Attendance'
admin.site.index_title = 'Organization Management'
