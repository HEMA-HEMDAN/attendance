from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from apps.accounts.models import Role
from apps.accounts.permissions import IsOrganizationAdmin, IsSuperadmin
from .models import Organization
from .serializers import OrganizationSerializer


class OrganizationListCreateView(generics.ListCreateAPIView):
    """
    GET: Superadmin lists all organizations; org admin lists only their own.
    POST: Superadmin only — organization admins cannot create tenants.
    """
    serializer_class = OrganizationSerializer

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsSuperadmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        qs = Organization.objects.all().order_by('name', 'id')
        if user.role == Role.SUPERADMIN:
            return qs
        if user.role == Role.ADMIN and user.organization_id:
            return qs.filter(pk=user.organization_id)
        return Organization.objects.none()


class OrganizationDetailView(generics.RetrieveUpdateAPIView):
    """Admin can view/update their own organization."""
    permission_classes = [IsOrganizationAdmin]
    serializer_class = OrganizationSerializer

    def get_object(self):
        return self.request.user.organization
