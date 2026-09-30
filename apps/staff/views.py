"""
Staff views — Doctor & Teaching Assistant endpoints.
"""

from rest_framework import generics, filters, status
from rest_framework.response import Response
from apps.accounts.permissions import IsOrganizationAdmin, IsStaffOrAdmin
from .models import Doctor, TeachingAssistant
from .serializers import (
    DoctorSerializer, TeachingAssistantSerializer,
    StaffChangePasswordSerializer, AdminResetStaffPasswordSerializer,
)


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


class StaffChangePasswordView(generics.GenericAPIView):
    """Allows staff member (Doctor, TA, or Admin) to change their own password."""
    permission_classes = [IsStaffOrAdmin]
    serializer_class = StaffChangePasswordSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save()
        return Response({'detail': 'Password successfully changed.'}, status=status.HTTP_200_OK)


class DoctorChangePasswordView(generics.GenericAPIView):
    """Allows Organization Admin to reset a specific Doctor's password."""
    permission_classes = [IsOrganizationAdmin]
    serializer_class = AdminResetStaffPasswordSerializer

    def post(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        doctor = generics.get_object_or_404(
            Doctor.objects.filter(organization=request.user.organization),
            pk=pk
        )
        doctor.user.set_password(serializer.validated_data['new_password'])
        doctor.user.save()
        return Response(
            {'detail': f"Password for Doctor {doctor.user.get_full_name()} reset successfully."},
            status=status.HTTP_200_OK
        )


class TeachingAssistantChangePasswordView(generics.GenericAPIView):
    """Allows Organization Admin to reset a specific TA's password."""
    permission_classes = [IsOrganizationAdmin]
    serializer_class = AdminResetStaffPasswordSerializer

    def post(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ta = generics.get_object_or_404(
            TeachingAssistant.objects.filter(organization=request.user.organization),
            pk=pk
        )
        ta.user.set_password(serializer.validated_data['new_password'])
        ta.user.save()
        return Response(
            {'detail': f"Password for TA {ta.user.get_full_name()} reset successfully."},
            status=status.HTTP_200_OK
        )

