from rest_framework import generics, filters
from apps.accounts.permissions import IsOrganizationAdmin, IsTeacherOrAdmin
from apps.accounts.models import Role
from .models import AcademicYear, Semester, Course, CourseOffering, Schedule, ScheduleException
from .serializers import (
    AcademicYearSerializer, SemesterSerializer, CourseSerializer,
    CourseOfferingSerializer, ScheduleSerializer, ScheduleExceptionSerializer,
)


class AcademicYearListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsTeacherOrAdmin]
    serializer_class = AcademicYearSerializer

    def get_queryset(self):
        return AcademicYear.objects.filter(organization=self.request.user.organization)


class SemesterListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsTeacherOrAdmin]
    serializer_class = SemesterSerializer

    def get_queryset(self):
        return Semester.objects.filter(organization=self.request.user.organization)


class CourseViewSet(generics.ListCreateAPIView):
    permission_classes = [IsTeacherOrAdmin]
    serializer_class = CourseSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'code']

    def get_queryset(self):
        return Course.objects.filter(organization=self.request.user.organization).order_by('name')


class CourseDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsOrganizationAdmin]
    serializer_class = CourseSerializer

    def get_queryset(self):
        return Course.objects.filter(organization=self.request.user.organization)


class CourseOfferingListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsTeacherOrAdmin]
    serializer_class = CourseOfferingSerializer

    def get_queryset(self):
        user = self.request.user
        qs = CourseOffering.objects.filter(
            course__organization=user.organization
        ).select_related('course', 'academic_year', 'semester', 'doctor__user').order_by('id')

        if user.role == Role.DOCTOR:
            qs = qs.filter(doctor__user=user)
        elif user.role == Role.TEACHING_ASSISTANT:
            qs = qs.filter(groups__teaching_assistant__user=user).distinct()

        return qs


class ScheduleListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsTeacherOrAdmin]
    serializer_class = ScheduleSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Schedule.objects.filter(
            course_offering__course__organization=user.organization
        ).select_related('course_offering__course', 'group')

        if user.role == Role.DOCTOR:
            qs = qs.filter(course_offering__doctor__user=user)
        elif user.role == Role.TEACHING_ASSISTANT:
            qs = qs.filter(group__teaching_assistant__user=user)

        return qs


class ScheduleExceptionListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsTeacherOrAdmin]
    serializer_class = ScheduleExceptionSerializer

    def get_queryset(self):
        return ScheduleException.objects.filter(
            schedule__course_offering__course__organization=self.request.user.organization
        )
