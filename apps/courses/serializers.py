from rest_framework import serializers
from apps.teachers.models import Teacher
from apps.groups.models import Group
from .models import Course


class CourseSerializer(serializers.ModelSerializer):
    teacher_name = serializers.SerializerMethodField()
    group_names = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = [
            'id', 'name', 'code', 'teacher', 'teacher_name',
            'groups', 'group_names', 'status', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request and request.user.organization_id:
            org = request.user.organization
            self.fields['teacher'].queryset = Teacher.objects.filter(organization=org)
            self.fields['groups'].queryset = Group.objects.filter(organization=org, status='ACTIVE')

    def get_teacher_name(self, obj):
        if obj.teacher:
            return obj.teacher.user.get_full_name()
        return None

    def get_group_names(self, obj):
        return list(obj.groups.values_list('name', flat=True))

    def create(self, validated_data):
        validated_data['organization'] = self.context['request'].user.organization
        return super().create(validated_data)
