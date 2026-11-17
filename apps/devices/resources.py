"""
django-import-export resources for Devices.
Export-only.
"""

from import_export import fields
from apps.accounts.resources import OrgScopedModelResource
from apps.devices.models import Device


class DeviceResource(OrgScopedModelResource):
    student_id = fields.Field(column_name='student_id')
    student_name = fields.Field(column_name='student_name')

    class Meta(OrgScopedModelResource.Meta):
        model = Device
        fields = ['id', 'student_id', 'student_name', 'platform', 'device_name', 'status', 'created_at']
        export_order = fields

    def dehydrate_student_id(self, obj):
        return obj.student.student_id if obj.student else ''

    def dehydrate_student_name(self, obj):
        return obj.student.user.get_full_name() if obj.student and obj.student.user else ''
