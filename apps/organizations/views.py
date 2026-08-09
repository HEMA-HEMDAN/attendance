from rest_framework import generics
from apps.accounts.permissions import IsOrganizationAdmin
from .serializers import OrganizationSerializer


class OrganizationDetailView(generics.RetrieveUpdateAPIView):
    """Admin can view/update their own organization."""
    permission_classes = [IsOrganizationAdmin]
    serializer_class = OrganizationSerializer

    def get_object(self):
        return self.request.user.organization
