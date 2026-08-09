from rest_framework import generics, filters, status
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from apps.accounts.permissions import IsOrganizationAdmin, IsAdminOrTeacher
from .models import Group
from .serializers import GroupSerializer


class GroupViewSet(ModelViewSet):
    permission_classes = [IsOrganizationAdmin]
    serializer_class = GroupSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']

    def get_queryset(self):
        return Group.objects.filter(
            organization=self.request.user.organization
        ).order_by('name')

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [IsAdminOrTeacher()]
        return [IsOrganizationAdmin()]
