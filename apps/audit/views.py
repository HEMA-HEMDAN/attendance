from rest_framework import generics, filters
from apps.accounts.permissions import IsOrganizationAdmin
from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogListView(generics.ListAPIView):
    """List audit logs for the admin's organization. Read-only."""
    permission_classes = [IsOrganizationAdmin]
    serializer_class = AuditLogSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['action', 'target_type', 'target_id']

    def get_queryset(self):
        qs = AuditLog.objects.filter(
            organization=self.request.user.organization
        ).select_related('actor').order_by('-created_at')

        action = self.request.query_params.get('action')
        if action:
            qs = qs.filter(action=action)

        return qs
