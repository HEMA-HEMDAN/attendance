from django.urls import path
from .views import (
    DoctorListCreateView, DoctorDetailView, DoctorChangePasswordView, DoctorAssignCoursesView, DoctorSchedulesView,
    TeachingAssistantListCreateView, TeachingAssistantDetailView, TeachingAssistantChangePasswordView, TAAssignGroupsView, TASchedulesView,
    StaffChangePasswordView,
)

urlpatterns = [
    path('change-password/', StaffChangePasswordView.as_view(), name='staff-change-password'),
    path('doctors/', DoctorListCreateView.as_view(), name='doctor-list-create'),
    path('doctors/<int:pk>/', DoctorDetailView.as_view(), name='doctor-detail'),
    path('doctors/<int:pk>/assign-courses/', DoctorAssignCoursesView.as_view(), name='doctor-assign-courses'),
    path('doctors/<int:pk>/schedules/', DoctorSchedulesView.as_view(), name='doctor-schedules'),
    path('doctors/<int:pk>/change-password/', DoctorChangePasswordView.as_view(), name='doctor-change-password'),
    path('assistants/', TeachingAssistantListCreateView.as_view(), name='ta-list-create'),
    path('assistants/<int:pk>/', TeachingAssistantDetailView.as_view(), name='ta-detail'),
    path('assistants/<int:pk>/assign-groups/', TAAssignGroupsView.as_view(), name='ta-assign-groups'),
    path('assistants/<int:pk>/schedules/', TASchedulesView.as_view(), name='ta-schedules'),
    path('assistants/<int:pk>/change-password/', TeachingAssistantChangePasswordView.as_view(), name='ta-change-password'),
]

