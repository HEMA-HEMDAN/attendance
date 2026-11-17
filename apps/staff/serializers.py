"""
Staff serializers — Doctor and TeachingAssistant management.
"""

from rest_framework import serializers
from django.db import transaction
from apps.accounts.models import User, Role
from apps.accounts.services.member_provisioning import MemberProvisioningService
from .models import Doctor, TeachingAssistant


class DoctorCourseOfferingSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    course_code = serializers.CharField(source='course.code', read_only=True)
    course_name = serializers.CharField(source='course.name', read_only=True)


class TACourseGroupSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField(read_only=True)
    course_code = serializers.CharField(source='course_offering.course.code', read_only=True)


class DoctorSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(source='user.first_name')
    last_name = serializers.CharField(source='user.last_name')
    email = serializers.EmailField(source='user.email')
    assigned_course_offerings = DoctorCourseOfferingSummarySerializer(source='course_offerings', many=True, read_only=True)

    class Meta:
        model = Doctor
        fields = ['id', 'user_id', 'email', 'first_name', 'last_name', 'department', 'title', 'assigned_course_offerings', 'created_at']
        read_only_fields = ['id', 'user_id', 'created_at', 'assigned_course_offerings']

    @transaction.atomic
    def create(self, validated_data):
        user_data = validated_data.pop('user')
        request = self.context.get('request')
        org = request.user.organization if request else None

        user, is_new = MemberProvisioningService.get_or_create_member_user(
            organization=org,
            email=user_data['email'],
            first_name=user_data['first_name'],
            last_name=user_data['last_name'],
            role=Role.DOCTOR,
        )
        if is_new:
            transaction.on_commit(lambda: MemberProvisioningService.send_activation_email(user.id))

        doctor = Doctor.objects.create(
            user=user,
            organization=org,
            **validated_data
        )
        return doctor


class TeachingAssistantSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(source='user.first_name')
    last_name = serializers.CharField(source='user.last_name')
    email = serializers.EmailField(source='user.email')
    assigned_groups = TACourseGroupSummarySerializer(many=True, read_only=True)

    class Meta:
        model = TeachingAssistant
        fields = ['id', 'user_id', 'email', 'first_name', 'last_name', 'department', 'assigned_groups', 'created_at']
        read_only_fields = ['id', 'user_id', 'created_at', 'assigned_groups']

    @transaction.atomic
    def create(self, validated_data):
        user_data = validated_data.pop('user')
        request = self.context.get('request')
        org = request.user.organization if request else None

        user, is_new = MemberProvisioningService.get_or_create_member_user(
            organization=org,
            email=user_data['email'],
            first_name=user_data['first_name'],
            last_name=user_data['last_name'],
            role=Role.TEACHING_ASSISTANT,
        )
        if is_new:
            transaction.on_commit(lambda: MemberProvisioningService.send_activation_email(user.id))

        ta = TeachingAssistant.objects.create(
            user=user,
            organization=org,
            **validated_data
        )
        return ta


class DoctorAssignCoursesSerializer(serializers.Serializer):
    course_offering_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=True
    )


class TAAssignGroupsSerializer(serializers.Serializer):
    group_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=True
    )


class StaffChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(write_only=True, min_length=8, required=True)

    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Incorrect current password.")
        return value


class AdminResetStaffPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True, min_length=8, required=True)

