"""Attendance serializers."""

from rest_framework import serializers
from django.utils import timezone
from datetime import timedelta

from apps.courses.models import Course
from apps.groups.models import Group
from apps.locations.models import AttendanceLocation
from .models import AttendanceSession, AttendanceRecord, SessionStatus


class AttendanceSessionSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True)
    group_name = serializers.CharField(source='group.name', read_only=True)
    teacher_name = serializers.SerializerMethodField()
    latitude = serializers.FloatField(read_only=True, allow_null=True)
    longitude = serializers.FloatField(read_only=True, allow_null=True)
    radius_meters = serializers.FloatField(read_only=True)
    present_count = serializers.SerializerMethodField()
    late_count = serializers.SerializerMethodField()
    total_enrolled = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceSession
        fields = [
            'id', 'course', 'course_name', 'group', 'group_name',
            'teacher_name', 'latitude', 'longitude', 'radius_meters',
            'status', 'starts_at', 'expires_at', 'closed_at',
            'biometric_required', 'location_required',
            'max_location_accuracy_meters', 'late_after_minutes', 'duration_minutes',
            'present_count', 'late_count', 'total_enrolled',
            'created_at',
        ]
        read_only_fields = [
            'id', 'status', 'starts_at', 'expires_at', 'closed_at',
            'created_at', 'course_name', 'group_name', 'teacher_name',
            'latitude', 'longitude', 'radius_meters',
            'present_count', 'late_count', 'total_enrolled',
        ]

    def get_teacher_name(self, obj):
        return obj.teacher.user.get_full_name() if obj.teacher else None

    def get_present_count(self, obj):
        return obj.records.filter(status='PRESENT').count()

    def get_late_count(self, obj):
        return obj.records.filter(status='LATE').count()

    def get_total_enrolled(self, obj):
        from apps.students.models import Student
        return Student.objects.filter(group=obj.group, status='ACTIVE').count()


class SessionCreateSerializer(serializers.Serializer):
    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.none())
    group = serializers.PrimaryKeyRelatedField(queryset=Group.objects.none(), required=False, allow_null=True)
    session_type = serializers.ChoiceField(choices=[('LECTURE', 'Lecture'), ('LAB', 'Lab'), ('TUTORIAL', 'Tutorial')], default='LECTURE')
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)
    radius_meters = serializers.FloatField(default=50.0)
    duration_minutes = serializers.IntegerField(default=60, min_value=1, max_value=480)
    biometric_required = serializers.BooleanField(default=True)
    location_required = serializers.BooleanField(default=True)
    max_location_accuracy_meters = serializers.FloatField(default=50.0)
    late_after_minutes = serializers.IntegerField(default=15)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request and request.user.organization_id:
            org = request.user.organization
            self.fields['course'].queryset = Course.objects.filter(
                organization=org, status='ACTIVE'
            )
            self.fields['group'].queryset = Group.objects.filter(
                organization=org, status='ACTIVE'
            )

    def validate(self, data):
        request = self.context['request']
        course = data['course']
        group = data.get('group')
        session_type = data.get('session_type', 'LECTURE')

        if session_type in ('LAB', 'TUTORIAL') and not group:
            raise serializers.ValidationError({'group': f'Group is required for a {session_type} session.'})

        if request.user.role == 'DOCTOR':
            teacher = request.user.teacher_profile
            if course.teacher != teacher:
                raise serializers.ValidationError('You are not the assigned doctor for this course.')
        elif request.user.role == 'TEACHING_ASSISTANT':
            teacher = request.user.teacher_profile
            if session_type == 'LECTURE':
                raise serializers.ValidationError('Teaching Assistants cannot create Lecture sessions.')
            if not group or group.teaching_assistant != teacher:
                raise serializers.ValidationError('You are not the assigned teaching assistant for this group.')

        if group and not course.groups.filter(pk=group.pk).exists():
            raise serializers.ValidationError('This group is not enrolled in the selected course')
            
        return data

    def create(self, validated_data):
        request = self.context['request']
        org = request.user.organization
        teacher = request.user.teacher_profile

        now = timezone.now()
        duration = validated_data.pop('duration_minutes', 60)
        expires_at = now + timedelta(minutes=duration)

        return AttendanceSession.objects.create(
            organization=org,
            teacher=teacher,
            starts_at=now,
            expires_at=expires_at,
            duration_minutes=duration,
            **validated_data,
        )


class CheckInRequestSerializer(serializers.Serializer):
    """Data submitted by student during attendance check-in."""
    device_id = serializers.IntegerField()
    challenge_token = serializers.CharField(max_length=128)
    signature = serializers.CharField(help_text='Base64-encoded RSA signature of challenge_token')

    # Location (raw data — server makes inside/outside decision)
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)
    location_accuracy = serializers.FloatField(required=False, allow_null=True)
    location_timestamp = serializers.FloatField(required=False, allow_null=True, help_text='Unix timestamp')
    mock_location = serializers.BooleanField(default=False)


class AttendanceRecordSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    student_id = serializers.CharField(source='student.student_id', read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = [
            'id', 'session', 'student', 'student_id', 'student_name',
            'status', 'verified_at',
            'location_accuracy_meters', 'distance_from_location_meters',
            'submitted_latitude', 'submitted_longitude',
            'mock_location_detected', 'device_challenge_verified',
            'created_at',
        ]
        read_only_fields = fields

    def get_student_name(self, obj):
        return obj.student.user.get_full_name()
