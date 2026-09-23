from django.urls import path
from .views import (
    DoctorListCreateView, DoctorDetailView,
    TeachingAssistantListCreateView, TeachingAssistantDetailView,
)

urlpatterns = [
    path('doctors/', DoctorListCreateView.as_view(), name='doctor-list-create'),
    path('doctors/<int:pk>/', DoctorDetailView.as_view(), name='doctor-detail'),
    path('assistants/', TeachingAssistantListCreateView.as_view(), name='ta-list-create'),
    path('assistants/<int:pk>/', TeachingAssistantDetailView.as_view(), name='ta-detail'),
]
