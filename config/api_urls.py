from django.urls import path, include

urlpatterns = [
    # Auth
    path('auth/', include('apps.accounts.urls')),

    # Organization management
    path('organizations/', include('apps.organizations.urls')),
    path('students/', include('apps.students.urls')),
    path('teachers/', include('apps.teachers.urls')),
    path('groups/', include('apps.groups.urls')),
    path('courses/', include('apps.courses.urls')),

    # Infrastructure
    path('devices/', include('apps.devices.urls')),
    path('locations/', include('apps.locations.urls')),

    # Attendance
    path('attendance/', include('apps.attendance.urls')),

    # Audit
    path('audit/', include('apps.audit.urls')),
]
