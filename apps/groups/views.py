from rest_framework import generics, filters
from rest_framework.viewsets import ModelViewSet
from apps.accounts.permissions import IsOrganizationAdmin, IsTeacherOrAdmin
from apps.accounts.models import Role
from .models import Group
from .serializers import GroupSerializer


class GroupViewSet(ModelViewSet):
    serializer_class = GroupSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'course_offering__course__code', 'course_offering__course__name']

    def get_queryset(self):
        user = self.request.user
        qs = Group.objects.filter(
            course_offering__course__organization=user.organization
        ).select_related('course_offering__course', 'teaching_assistant__user').order_by('name')

        if user.role == Role.TEACHING_ASSISTANT:
            qs = qs.filter(teaching_assistant__user=user)
        elif user.role == Role.DOCTOR:
            qs = qs.filter(course_offering__doctor__user=user)

        return qs

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [IsTeacherOrAdmin()]
        return [IsOrganizationAdmin()]
