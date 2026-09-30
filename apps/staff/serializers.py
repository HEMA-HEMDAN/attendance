"""
Staff serializers — Doctor and TeachingAssistant management.
"""

from rest_framework import serializers
from django.db import transaction
from apps.accounts.models import User, Role
from .models import Doctor, TeachingAssistant


class DoctorSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(source='user.first_name')
    last_name = serializers.CharField(source='user.last_name')
    email = serializers.EmailField(source='user.email')

    class Meta:
        model = Doctor
        fields = ['id', 'user_id', 'email', 'first_name', 'last_name', 'department', 'title', 'created_at']
        read_only_fields = ['id', 'user_id', 'created_at']

    @transaction.atomic
    def create(self, validated_data):
        user_data = validated_data.pop('user')
        request = self.context.get('request')
        org = request.user.organization if request else None

        user = User.objects.create_user(
            email=user_data['email'],
            password='Password123!',
            first_name=user_data['first_name'],
            last_name=user_data['last_name'],
            role=Role.DOCTOR,
            organization=org,
        )
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

    class Meta:
        model = TeachingAssistant
        fields = ['id', 'user_id', 'email', 'first_name', 'last_name', 'department', 'created_at']
        read_only_fields = ['id', 'user_id', 'created_at']

    @transaction.atomic
    def create(self, validated_data):
        user_data = validated_data.pop('user')
        request = self.context.get('request')
        org = request.user.organization if request else None

        user = User.objects.create_user(
            email=user_data['email'],
            password='Password123!',
            first_name=user_data['first_name'],
            last_name=user_data['last_name'],
            role=Role.TEACHING_ASSISTANT,
            organization=org,
        )
        ta = TeachingAssistant.objects.create(
            user=user,
            organization=org,
            **validated_data
        )
        return ta


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

