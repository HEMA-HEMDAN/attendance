from rest_framework import serializers
from apps.staff.models import Doctor
from .models import AcademicYear, Semester, Course, CourseOffering, Schedule, ScheduleException


class AcademicYearSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicYear
        fields = ['id', 'name', 'start_date', 'end_date', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']

    def create(self, validated_data):
        validated_data['organization'] = self.context['request'].user.organization
        return super().create(validated_data)


class SemesterSerializer(serializers.ModelSerializer):
    academic_year_name = serializers.CharField(source='academic_year.name', read_only=True)

    class Meta:
        model = Semester
        fields = ['id', 'academic_year', 'academic_year_name', 'name', 'start_date', 'end_date', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']

    def create(self, validated_data):
        validated_data['organization'] = self.context['request'].user.organization
        return super().create(validated_data)


class CourseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ['id', 'code', 'name', 'department', 'created_at']
        read_only_fields = ['id', 'created_at']

    def create(self, validated_data):
        validated_data['organization'] = self.context['request'].user.organization
        return super().create(validated_data)


class CourseOfferingSerializer(serializers.ModelSerializer):
    course_code = serializers.CharField(source='course.code', read_only=True)
    course_name = serializers.CharField(source='course.name', read_only=True)
    academic_year_name = serializers.CharField(source='academic_year.name', read_only=True)
    semester_name = serializers.CharField(source='semester.name', read_only=True)
    doctor_name = serializers.SerializerMethodField()

    class Meta:
        model = CourseOffering
        fields = [
            'id', 'course', 'course_code', 'course_name',
            'academic_year', 'academic_year_name',
            'semester', 'semester_name',
            'doctor', 'doctor_name', 'status', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def get_doctor_name(self, obj):
        if obj.doctor:
            return obj.doctor.user.get_full_name()
        return None


class ScheduleSerializer(serializers.ModelSerializer):
    course_code = serializers.CharField(source='course_offering.course.code', read_only=True)
    group_name = serializers.CharField(source='group.name', read_only=True, default=None)

    class Meta:
        model = Schedule
        fields = [
            'id', 'course_offering', 'course_code', 'group', 'group_name',
            'session_type', 'location', 'day_of_week', 'start_time', 'end_time',
            'effective_from', 'effective_until', 'is_active', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class ScheduleExceptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduleException
        fields = ['id', 'schedule', 'date', 'exception_type', 'reason', 'new_start_time', 'new_end_time', 'created_at']
        read_only_fields = ['id', 'created_at']
