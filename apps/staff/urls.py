from django.urls import path
from .views import (
    DoctorListCreateView, DoctorDetailView, DoctorChangePasswordView,
    TeachingAssistantListCreateView, TeachingAssistantDetailView, TeachingAssistantChangePasswordView,
    StaffChangePasswordView,
)

urlpatterns = [
    path('change-password/', StaffChangePasswordView.as_view(), name='staff-change-password'),
    path('doctors/', DoctorListCreateView.as_view(), name='doctor-list-create'),
    path('doctors/<int:pk>/', DoctorDetailView.as_view(), name='doctor-detail'),
    path('doctors/<int:pk>/change-password/', DoctorChangePasswordView.as_view(), name='doctor-change-password'),
    path('assistants/', TeachingAssistantListCreateView.as_view(), name='ta-list-create'),
    path('assistants/<int:pk>/', TeachingAssistantDetailView.as_view(), name='ta-detail'),
    path('assistants/<int:pk>/change-password/', TeachingAssistantChangePasswordView.as_view(), name='ta-change-password'),
]

