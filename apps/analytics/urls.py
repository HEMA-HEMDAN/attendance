from django.urls import path
from .views import (
    DoctorAnalyticsView, TeachingAssistantAnalyticsView,
    OrganizationAdminAnalyticsView, SuperadminAnalyticsView,
    AnalyticsDashboardWebView,
)

urlpatterns = [
    path('dashboard/', AnalyticsDashboardWebView.as_view(), name='analytics-dashboard'),
    path('doctor/', DoctorAnalyticsView.as_view(), name='analytics-doctor'),
    path('ta/', TeachingAssistantAnalyticsView.as_view(), name='analytics-ta'),
    path('admin/', OrganizationAdminAnalyticsView.as_view(), name='analytics-admin'),
    path('superadmin/', SuperadminAnalyticsView.as_view(), name='analytics-superadmin'),
]

