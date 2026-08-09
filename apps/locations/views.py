from rest_framework import generics, filters
from apps.accounts.permissions import IsOrganizationAdmin, IsAdminOrTeacher
from .models import AttendanceLocation
from .serializers import AttendanceLocationSerializer


class LocationListCreateView(generics.ListCreateAPIView):
    serializer_class = AttendanceLocationSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAdminOrTeacher()]
        return [IsOrganizationAdmin()]

    def get_queryset(self):
        return AttendanceLocation.objects.filter(
            organization=self.request.user.organization,
        ).order_by('name')


class LocationDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsOrganizationAdmin]
    serializer_class = AttendanceLocationSerializer
    http_method_names = ['get', 'patch', 'delete']

    def get_queryset(self):
        return AttendanceLocation.objects.filter(
            organization=self.request.user.organization
        )
