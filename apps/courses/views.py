from rest_framework import generics, filters
from apps.accounts.permissions import IsOrganizationAdmin, IsAdminOrTeacher
from .models import Course
from .serializers import CourseSerializer


class CourseViewSet(generics.ListCreateAPIView):
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'code']

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAdminOrTeacher()]
        return [IsOrganizationAdmin()]

    def get_serializer_class(self):
        return CourseSerializer

    def get_queryset(self):
        qs = Course.objects.filter(
            organization=self.request.user.organization
        ).select_related('teacher__user').prefetch_related('groups').order_by('name')

        if self.request.user.is_teacher:
            qs = qs.filter(teacher__user=self.request.user)

        return qs


class CourseDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsOrganizationAdmin]
    serializer_class = CourseSerializer
    http_method_names = ['get', 'patch', 'delete']

    def get_queryset(self):
        return Course.objects.filter(
            organization=self.request.user.organization
        ).select_related('teacher__user').prefetch_related('groups')
