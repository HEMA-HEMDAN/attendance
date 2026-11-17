from rest_framework import serializers
from .models import Group


class GroupSerializer(serializers.ModelSerializer):
    course_code = serializers.CharField(source='course_offering.course.code', read_only=True)
    ta_name = serializers.SerializerMethodField()
    student_count = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = [
            'id', 'course_offering', 'course_code', 'name',
            'teaching_assistant', 'ta_name', 'status',
            'student_count', 'created_at',
        ]
        read_only_fields = ['id', 'created_at', 'student_count']

    def get_ta_name(self, obj):
        if obj.teaching_assistant:
            return obj.teaching_assistant.user.get_full_name()
        return None

    def get_student_count(self, obj):
        return obj.enrollments.filter(student__status='ACTIVE').count()
