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
            'group_id', 'group_name', 'scheduled_date', 'starts_at', 'ends_at',
            'session_type', 'status',
        ]


class AttendanceSessionSerializer(serializers.ModelSerializer):
    course_code = serializers.CharField(source='occurrence.course_offering.course.code', read_only=True)
    course_name = serializers.CharField(source='occurrence.course_offering.course.name', read_only=True)
    group_name = serializers.CharField(source='occurrence.group.name', read_only=True, default=None)
    session_type = serializers.CharField(source='occurrence.session_type', read_only=True)

    class Meta:
        model = AttendanceSession
        fields = [
            'id', 'occurrence_id', 'course_code', 'course_name', 'group_name',
            'session_type', 'latitude', 'longitude', 'radius_meters',
            'max_location_accuracy_meters', 'late_after_minutes', 'status',
            'starts_at', 'expires_at', 'closed_at', 'created_at',
        ]


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
