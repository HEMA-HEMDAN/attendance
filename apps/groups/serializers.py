from rest_framework import serializers
from .models import Group


class GroupSerializer(serializers.ModelSerializer):
    student_count = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = ['id', 'name', 'status', 'student_count', 'created_at']
        read_only_fields = ['id', 'created_at', 'student_count']

    def get_student_count(self, obj):
        return obj.enrollments.filter(student__status='ACTIVE').count()

    def create(self, validated_data):
        validated_data['organization'] = self.context['request'].user.organization
        return super().create(validated_data)
