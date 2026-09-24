"""
Staff views — Doctor & Teaching Assistant endpoints.
"""

from rest_framework import generics, filters
from apps.accounts.permissions import IsOrganizationAdmin
from .models import Doctor, TeachingAssistant
from .serializers import DoctorSerializer, TeachingAssistantSerializer


class DoctorListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsOrganizationAdmin]
    serializer_class = DoctorSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['user__first_name', 'user__last_name', 'user__email', 'department']

    def get_queryset(self):
        return Doctor.objects.filter(
            organization=self.request.user.organization
        ).select_related('user').order_by('user__first_name')


class DoctorDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsOrganizationAdmin]
    serializer_class = DoctorSerializer

    def get_queryset(self):
        return Doctor.objects.filter(
            organization=self.request.user.organization
        ).select_related('user')


class TeachingAssistantListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsOrganizationAdmin]
    serializer_class = TeachingAssistantSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['user__first_name', 'user__last_name', 'user__email', 'department']

    def get_queryset(self):
        return TeachingAssistant.objects.filter(
            organization=self.request.user.organization
        ).select_related('user').order_by('user__first_name')


class TeachingAssistantDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsOrganizationAdmin]
    serializer_class = TeachingAssistantSerializer

    def get_queryset(self):
        return TeachingAssistant.objects.filter(
            organization=self.request.user.organization
        ).select_related('user')
