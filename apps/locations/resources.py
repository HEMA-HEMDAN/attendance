"""
django-import-export resources for Locations app.
"""

from apps.accounts.resources import OrgScopedModelResource
from apps.locations.models import AttendanceLocation


class AttendanceLocationResource(OrgScopedModelResource):
    class Meta(OrgScopedModelResource.Meta):
        model = AttendanceLocation
        import_id_fields = ['name']
        fields = ['name', 'latitude', 'longitude', 'radius_meters', 'status']
        export_order = ['name', 'latitude', 'longitude', 'radius_meters', 'status']

    def get_instance(self, instance_loader, row):
        name = row.get('name')
        if not name:
            return None
        return self.get_queryset().filter(name=name).first()

    def init_instance(self, row=None):
        instance = super().init_instance(row=row)
        if self.organization:
            instance.organization = self.organization
        return instance
