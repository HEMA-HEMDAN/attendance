"""
django-import-export resources for Audit logs.
Export-only.
"""

from import_export import fields
from apps.accounts.resources import OrgScopedModelResource
from apps.audit.models import AuditLog


class AuditLogResource(OrgScopedModelResource):
    actor_email = fields.Field(column_name='actor_email')

    class Meta(OrgScopedModelResource.Meta):
        model = AuditLog
        fields = ['id', 'action', 'actor_email', 'target_type', 'target_id', 'ip_address', 'created_at']
        export_order = fields

    def dehydrate_actor_email(self, obj):
        return obj.actor.email if obj.actor else ''
