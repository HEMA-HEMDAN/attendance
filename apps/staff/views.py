"""
Staff views — Doctor & Teaching Assistant endpoints.
"""

from rest_framework import generics, filters, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from apps.accounts.permissions import IsOrganizationAdmin, IsStaffOrAdmin
from apps.courses.serializers import ScheduleSerializer
from .models import Doctor, TeachingAssistant
from .serializers import (
    DoctorSerializer, TeachingAssistantSerializer,
    StaffChangePasswordSerializer, AdminResetStaffPasswordSerializer,
    DoctorAssignCoursesSerializer, TAAssignGroupsSerializer,
)


class FlexiblePageNumberPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 1000


class DoctorListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsOrganizationAdmin]
    serializer_class = DoctorSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['user__first_name', 'user__last_name', 'user__email', 'department']
    pagination_class = FlexiblePageNumberPagination

    def get_queryset(self):
        return Doctor.objects.filter(
            organization=self.request.user.organization
        ).select_related('user').prefetch_related('course_offerings__course').order_by('user__first_name')


class DoctorDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsOrganizationAdmin]
    serializer_class = DoctorSerializer

    def get_queryset(self):
        return Doctor.objects.filter(
            organization=self.request.user.organization
        ).select_related('user').prefetch_related('course_offerings__course')


class TeachingAssistantListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsOrganizationAdmin]
    serializer_class = TeachingAssistantSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['user__first_name', 'user__last_name', 'user__email', 'department']
    pagination_class = FlexiblePageNumberPagination

    def get_queryset(self):
        return TeachingAssistant.objects.filter(
            organization=self.request.user.organization
        ).select_related('user').prefetch_related('assigned_groups__course_offering__course').order_by('user__first_name')


class TeachingAssistantDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsOrganizationAdmin]
    serializer_class = TeachingAssistantSerializer

    def get_queryset(self):
        return TeachingAssistant.objects.filter(
            organization=self.request.user.organization
        ).select_related('user').prefetch_related('assigned_groups__course_offering__course')


class DoctorAssignCoursesView(generics.GenericAPIView):
    """Bulk assign course offerings to a Doctor."""
    permission_classes = [IsOrganizationAdmin]
    serializer_class = DoctorAssignCoursesSerializer

    def post(self, request, pk):
        from django.db import transaction
        from apps.courses.models import CourseOffering

        doctor = generics.get_object_or_404(
            Doctor.objects.filter(organization=request.user.organization),
            pk=pk
        )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        offering_ids = serializer.validated_data['course_offering_ids']
        offerings = CourseOffering.objects.filter(
            id__in=offering_ids,
            course__organization=request.user.organization
        )
        if len(offerings) != len(offering_ids):
            return Response(
                {'detail': 'One or more course offerings were not found in your organization.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            CourseOffering.objects.filter(doctor=doctor).update(doctor=None)
            offerings.update(doctor=doctor)

        return Response(DoctorSerializer(doctor).data, status=status.HTTP_200_OK)


class TAAssignGroupsView(generics.GenericAPIView):
    """Bulk assign lab groups to a Teaching Assistant."""
    permission_classes = [IsOrganizationAdmin]
    serializer_class = TAAssignGroupsSerializer

    def post(self, request, pk):
        from django.db import transaction
        from apps.groups.models import Group

        ta = generics.get_object_or_404(
            TeachingAssistant.objects.filter(organization=request.user.organization),
            pk=pk
        )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        group_ids = serializer.validated_data['group_ids']
        groups = Group.objects.filter(
            id__in=group_ids,
            course_offering__course__organization=request.user.organization
        )
        if len(groups) != len(group_ids):
            return Response(
                {'detail': 'One or more groups were not found in your organization.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            Group.objects.filter(teaching_assistant=ta).update(teaching_assistant=None)
            groups.update(teaching_assistant=ta)

        return Response(TeachingAssistantSerializer(ta).data, status=status.HTTP_200_OK)


class DoctorSchedulesView(generics.ListAPIView):
    """Retrieve all weekly schedules for course offerings led by a specific Doctor."""
    permission_classes = [IsStaffOrAdmin]
    serializer_class = ScheduleSerializer
    pagination_class = FlexiblePageNumberPagination

    def get_queryset(self):
        doctor_id = self.kwargs['pk']
        from apps.courses.models import Schedule
        return Schedule.objects.filter(
            course_offering__doctor_id=doctor_id,
            course_offering__course__organization=self.request.user.organization,
            is_active=True,
        ).select_related('course_offering__course', 'course_offering__doctor__user', 'group__teaching_assistant__user', 'location').order_by('day_of_week', 'start_time')


class TASchedulesView(generics.ListAPIView):
    """Retrieve all weekly schedules for groups assigned to a specific Teaching Assistant."""
    permission_classes = [IsStaffOrAdmin]
    serializer_class = ScheduleSerializer
    pagination_class = FlexiblePageNumberPagination

    def get_queryset(self):
        ta_id = self.kwargs['pk']
        from apps.courses.models import Schedule
        return Schedule.objects.filter(
            group__teaching_assistant_id=ta_id,
            course_offering__course__organization=self.request.user.organization,
            is_active=True,
        ).select_related('course_offering__course', 'course_offering__doctor__user', 'group__teaching_assistant__user', 'location').order_by('day_of_week', 'start_time')


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

