"""
Device serializers.

Device registration flow:
  1. Mobile generates RSA-2048 key pair
  2. Private key stored in Expo SecureStore (stays on device)
  3. Public key + device fingerprint POSTed to /devices/register/
  4. Server stores public key — used later to verify signed challenges

Security note: This is software-level key storage in Expo SDK 54.
Not hardware attestation (TEE/HSM). Documented limitation.
"""

from rest_framework import serializers
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.backends import default_backend
from .models import Device, DevicePlatform


class DeviceRegistrationSerializer(serializers.Serializer):
    device_fingerprint = serializers.CharField(max_length=512)
    public_key = serializers.CharField(help_text='PEM-encoded RSA public key')
    platform = serializers.ChoiceField(choices=DevicePlatform.choices, default=DevicePlatform.UNKNOWN)
    device_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    os_version = serializers.CharField(max_length=50, required=False, allow_blank=True)

    def validate_device_fingerprint(self, value):
        request = self.context.get('request')
        if request and hasattr(request.user, 'student_profile'):
            student = request.user.student_profile
            org = request.user.organization

            # Reject if this physical device fingerprint is currently ACTIVE under another student account
            other_active_device = Device.objects.filter(
                organization=org,
                device_fingerprint=value,
                status='ACTIVE',
            ).exclude(student=student).first()

            if other_active_device:
                raise serializers.ValidationError(
                    'This device is already registered to another student. Multi-account device sharing is prohibited.'
                )
        return value

    def validate_public_key(self, value):
        try:
            key = load_pem_public_key(value.encode(), backend=default_backend())
            # Must be RSA with at least 2048 bits
            if hasattr(key, 'key_size') and key.key_size < 2048:
                raise serializers.ValidationError('Key must be at least RSA-2048')
        except (ValueError, TypeError) as exc:
            raise serializers.ValidationError(f'Invalid public key: {exc}')
        return value

    def create(self, validated_data):
        from django.utils import timezone
        student = self.context['request'].user.student_profile
        org = self.context['request'].user.organization

        # Revoke any previous active devices for THIS student (1 student = 1 active device)
        Device.objects.filter(
            student=student,
            status='ACTIVE',
        ).update(status='REVOKED', revoked_at=timezone.now())

        return Device.objects.create(
            student=student,
            organization=org,
            **validated_data,
        )


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = [
            'id', 'device_fingerprint', 'platform', 'device_name',
            'os_version', 'status', 'registered_at', 'last_seen_at',
            'biometric_invalidated',
        ]
        read_only_fields = fields
