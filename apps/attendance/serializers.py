"""
Attendance serializers.
"""

from rest_framework import serializers
from .models import AttendanceSession, AttendanceRecord, SessionOccurrence


class SessionOccurrenceSerializer(serializers.ModelSerializer):
    course_code = serializers.CharField(source='course_offering.course.code', read_only=True)
    course_name = serializers.CharField(source='course_offering.course.name', read_only=True)
    group_name = serializers.CharField(source='group.name', read_only=True, default=None)

    class Meta:
        model = SessionOccurrence
        fields = [
            'id', 'schedule_id', 'course_offering_id', 'course_code', 'course_name',
            'group_id', 'group_name', 'occurrence_type', 'scheduled_date', 'starts_at', 'ends_at',
            'session_type', 'status',
        ]


class AttendanceSessionSerializer(serializers.ModelSerializer):
    course_offering_id = serializers.IntegerField(source='occurrence.course_offering_id', read_only=True)
    group_id = serializers.IntegerField(source='occurrence.group_id', read_only=True)
    course_code = serializers.CharField(source='occurrence.course_offering.course.code', read_only=True)
    course_name = serializers.CharField(source='occurrence.course_offering.course.name', read_only=True)
    group_name = serializers.CharField(source='occurrence.group.name', read_only=True, default=None)
    session_type = serializers.CharField(source='occurrence.session_type', read_only=True)
    occurrence_type = serializers.CharField(source='occurrence.occurrence_type', read_only=True)
    opened_by_name = serializers.CharField(source='opened_by.get_full_name', read_only=True)
    opened_at = serializers.DateTimeField(source='starts_at', read_only=True)

    class Meta:
        model = AttendanceSession
        fields = [
            'id', 'occurrence_id', 'course_offering_id', 'group_id', 'course_code', 'course_name', 'group_name',
            'session_type', 'occurrence_type', 'opened_by', 'opened_by_name', 'opened_at',
            'latitude', 'longitude', 'location_accuracy_meters', 'location_captured_at',
            'radius_meters', 'max_location_accuracy_meters', 'late_after_minutes', 'status',
            'starts_at', 'expires_at', 'closed_at', 'created_at',
        ]


class AdHocSessionStartSerializer(serializers.Serializer):
    course_offering_id = serializers.IntegerField()
    group_id = serializers.IntegerField(required=False, allow_null=True)
    session_type = serializers.ChoiceField(choices=['LECTURE', 'LAB', 'TUTORIAL'], default='LECTURE')
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    accuracy_m = serializers.FloatField(required=False, allow_null=True)
    location_accuracy_meters = serializers.FloatField(required=False, allow_null=True)
    location_captured_at = serializers.CharField(required=False, allow_null=True)
    captured_at = serializers.CharField(required=False, allow_null=True)
    radius_meters = serializers.FloatField(required=False, default=50.0, allow_null=True)

    def validate(self, attrs):
        if attrs.get('accuracy_m') is not None and not attrs.get('location_accuracy_meters'):
            attrs['location_accuracy_meters'] = attrs['accuracy_m']
        if attrs.get('captured_at') is not None and not attrs.get('location_captured_at'):
            attrs['location_captured_at'] = attrs['captured_at']
        radius = attrs.get('radius_meters')
        if radius is not None and (radius <= 0 or radius > 500.0):
            attrs['radius_meters'] = 50.0
        return attrs



class CheckInRequestSerializer(serializers.Serializer):
    device_id = serializers.IntegerField()
    challenge_token = serializers.CharField(max_length=128)
    signature = serializers.CharField()
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)
    location_accuracy = serializers.FloatField(required=False, allow_null=True)
    location_timestamp = serializers.FloatField(required=False, allow_null=True)
    mock_location = serializers.BooleanField(default=False)


class AttendanceRecordSerializer(serializers.ModelSerializer):
    student_id = serializers.CharField(source='student.student_id', read_only=True)
    student_name = serializers.CharField(source='student.user.get_full_name', read_only=True)
    course_code = serializers.CharField(source='session.occurrence.course_offering.course.code', read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = [
            'id', 'session_id', 'student_id', 'student_name', 'course_code',
            'status', 'verified_at', 'submitted_latitude', 'submitted_longitude',
            'location_accuracy_meters', 'distance_from_location_meters',
            'mock_location_detected', 'device_challenge_verified',
        ]
