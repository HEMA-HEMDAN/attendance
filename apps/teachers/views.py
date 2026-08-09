from rest_framework import generics, filters
from apps.accounts.permissions import IsOrganizationAdmin, IsAdminOrTeacher
from .models import Teacher
from .serializers import TeacherSerializer, TeacherCreateSerializer


class TeacherListCreateView(generics.ListCreateAPIView):
    filter_backends = [filters.SearchFilter]
    search_fields = ['user__first_name', 'user__last_name', 'user__email']

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAdminOrTeacher()]
        return [IsOrganizationAdmin()]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return TeacherCreateSerializer
        return TeacherSerializer

    def get_queryset(self):
        return Teacher.objects.filter(
            organization=self.request.user.organization
        ).select_related('user').order_by('user__last_name')


class TeacherDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsOrganizationAdmin]
    serializer_class = TeacherSerializer
    http_method_names = ['get', 'patch', 'delete']

    def get_queryset(self):
        return Teacher.objects.filter(
            organization=self.request.user.organization
        ).select_related('user')

    def perform_destroy(self, instance):
        instance.user.is_active = False
        instance.user.save()
