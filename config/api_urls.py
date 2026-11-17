from django.urls import path, include

urlpatterns = [
    # Auth
    path('auth/', include('apps.accounts.urls')),

    # Organization management
    path('organizations/', include('apps.organizations.urls')),
    path('students/', include('apps.students.urls')),
    path('staff/', include('apps.staff.urls')),
    path('groups/', include('apps.groups.urls')),
    path('courses/', include('apps.courses.urls')),

    # Infrastructure
    path('devices/', include('apps.devices.urls')),
    path('locations/', include('apps.locations.urls')),

    # Attendance & Analytics
    path('attendance/', include('apps.attendance.urls')),
    path('analytics/', include('apps.analytics.urls')),

    # Audit
    path('audit/', include('apps.audit.urls')),
]
