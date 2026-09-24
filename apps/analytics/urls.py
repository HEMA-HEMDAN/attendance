from django.urls import path
from .views import (
    DoctorAnalyticsView, TeachingAssistantAnalyticsView,
    OrganizationAdminAnalyticsView, SuperadminAnalyticsView,
    AnalyticsDashboardWebView,
    AnalyticsStudentListView, AnalyticsStudentDetailView,
    AnalyticsSessionAttendanceView, AnalyticsExportView,
)

urlpatterns = [
    path('dashboard/', AnalyticsDashboardWebView.as_view(), name='analytics-dashboard'),
    path('doctor/', DoctorAnalyticsView.as_view(), name='analytics-doctor'),
    path('ta/', TeachingAssistantAnalyticsView.as_view(), name='analytics-ta'),
    path('admin/', OrganizationAdminAnalyticsView.as_view(), name='analytics-admin'),
    path('superadmin/', SuperadminAnalyticsView.as_view(), name='analytics-superadmin'),
    path('students/', AnalyticsStudentListView.as_view(), name='analytics-students'),
    path('students/<int:student_id>/', AnalyticsStudentDetailView.as_view(), name='analytics-student-detail'),
    path('sessions/<int:session_id>/attendance/', AnalyticsSessionAttendanceView.as_view(), name='analytics-session-attendance'),
    path('export/<str:export_type>/', AnalyticsExportView.as_view(), name='analytics-export'),
]

