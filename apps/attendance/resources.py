"""
django-import-export resources for Attendance (Sessions, Records).
Export-only.
"""

from import_export import fields
from apps.accounts.resources import OrgScopedModelResource
from apps.attendance.models import AttendanceSession, AttendanceRecord


class AttendanceSessionResource(OrgScopedModelResource):
    opened_by_email = fields.Field(column_name='opened_by_email')
    course_code = fields.Field(column_name='course_code')
    session_type = fields.Field(column_name='session_type')
    scheduled_date = fields.Field(column_name='scheduled_date')

    class Meta(OrgScopedModelResource.Meta):
        model = AttendanceSession
        fields = [
            'id', 'course_code', 'session_type', 'scheduled_date',
            'opened_by_email', 'status', 'created_at'
        ]
        export_order = fields

    def dehydrate_opened_by_email(self, obj):
        return obj.opened_by.email if obj.opened_by else ''

    def dehydrate_course_code(self, obj):
        return obj.occurrence.course_offering.course.code if obj.occurrence and obj.occurrence.course_offering and obj.occurrence.course_offering.course else ''

    def dehydrate_session_type(self, obj):
        return obj.occurrence.session_type if obj.occurrence else ''

    def dehydrate_scheduled_date(self, obj):
        return str(obj.occurrence.scheduled_date) if obj.occurrence else ''


class AttendanceRecordResource(OrgScopedModelResource):
    org_field_lookup = 'session__organization'

    session_id = fields.Field(column_name='session_id', attribute='session_id')
    student_id = fields.Field(column_name='student_id')
    student_name = fields.Field(column_name='student_name')
    status = fields.Field(column_name='status', attribute='status')
    verified_at = fields.Field(column_name='verified_at', attribute='verified_at')
    distance_meters = fields.Field(column_name='distance_meters', attribute='distance_from_location_meters')

    class Meta(OrgScopedModelResource.Meta):
        model = AttendanceRecord
        fields = ['id', 'session_id', 'student_id', 'student_name', 'status', 'verified_at', 'distance_meters']
        export_order = fields

    def dehydrate_student_id(self, obj):
        return obj.student.student_id if obj.student else ''

    def dehydrate_student_name(self, obj):
        return obj.student.user.get_full_name() if obj.student and obj.student.user else ''
