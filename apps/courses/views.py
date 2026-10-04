from rest_framework import generics, filters
from rest_framework.pagination import PageNumberPagination
from apps.accounts.permissions import IsOrganizationAdmin, IsTeacherOrAdmin
from apps.accounts.models import Role
from .models import AcademicYear, Semester, Course, CourseOffering, Schedule, ScheduleException
from .serializers import (
    AcademicYearSerializer, SemesterSerializer, CourseSerializer,
    CourseOfferingSerializer, ScheduleSerializer, ScheduleExceptionSerializer,
)


class FlexiblePageNumberPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 1000


class AcademicYearListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsTeacherOrAdmin]
    serializer_class = AcademicYearSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']
    pagination_class = FlexiblePageNumberPagination

    def get_queryset(self):
        return AcademicYear.objects.filter(organization=self.request.user.organization)


class SemesterListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsTeacherOrAdmin]
    serializer_class = SemesterSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']
    pagination_class = FlexiblePageNumberPagination

    def get_queryset(self):
        return Semester.objects.filter(organization=self.request.user.organization)


class CourseViewSet(generics.ListCreateAPIView):
    permission_classes = [IsTeacherOrAdmin]
    serializer_class = CourseSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'code']
    pagination_class = FlexiblePageNumberPagination

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
    filter_backends = [filters.SearchFilter]
    search_fields = ['course__code', 'course__name', 'doctor__user__first_name', 'doctor__user__last_name']
    pagination_class = FlexiblePageNumberPagination

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
    filter_backends = [filters.SearchFilter]
    search_fields = ['course_offering__course__code', 'course_offering__course__name', 'group__name']
    pagination_class = FlexiblePageNumberPagination

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
    filter_backends = [filters.SearchFilter]
    search_fields = ['schedule__course_offering__course__code', 'reason']
    pagination_class = FlexiblePageNumberPagination

    def get_queryset(self):
        return ScheduleException.objects.filter(
            schedule__course_offering__course__organization=self.request.user.organization
        )
