"""
Custom django-import-export widgets for multi-tenant isolation.
"""

from import_export.widgets import ForeignKeyWidget
from django.core.exceptions import ObjectDoesNotExist


class OrgForeignKeyWidget(ForeignKeyWidget):
    """
    Tenant-scoped ForeignKeyWidget.
    Ensures foreign-key lookups are strictly isolated to the resource's organization.
    """

    def __init__(self, model, field='pk', resource=None, org_field='organization', **kwargs):
        self.resource = resource
        self.org_field = org_field
        super().__init__(model, field=field, **kwargs)

    def get_queryset(self, value, row, *args, **kwargs):
        qs = super().get_queryset(value, row, *args, **kwargs)
        org = None
        if self.resource and hasattr(self.resource, 'organization'):
            org = self.resource.organization

        if org is not None:
            return qs.filter(**{self.org_field: org})
        elif self.resource and getattr(self.resource, 'is_superuser', False):
            return qs
        # If no organization is set and not a superuser, return empty queryset
        return qs.none() if self.resource else qs

    def clean(self, value, row=None, **kwargs):
        if not value:
            return None
        val = str(value).strip()
        if not val:
            return None
        return super().clean(val, row=row, **kwargs)
