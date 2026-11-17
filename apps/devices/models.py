"""
Devices app.

A Device is a registered mobile device belonging to a student.
Device registration uses a public/private key pair:
  - The device generates the key pair
  - The private key never leaves the device (stored in platform SecureStore)
  - The server stores the public key and uses it to verify signed challenges

Security note:
  In Expo SDK 54 / Expo Go, key material is stored in Expo SecureStore (software
  secure enclave on many devices). This is NOT hardware attestation (TEE/HSM).
  The architecture is designed for future upgrade to hardware-bound keys.
  We document this limitation explicitly rather than overstating the security level.
"""

from django.db import models


class DeviceStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    REVOKED = 'REVOKED', 'Revoked'


class DevicePlatform(models.TextChoices):
    ANDROID = 'android', 'Android'
    IOS = 'ios', 'iOS'
    UNKNOWN = 'unknown', 'Unknown'


class Device(models.Model):
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='devices',
    )
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='devices',
    )

    # A stable identifier for the device (e.g. Expo device ID / application instance ID).
    # This is used as a loose hint only — not a security boundary.
    device_fingerprint = models.CharField(max_length=512)

    # PEM-encoded RSA public key. The private key never reaches the server.
    public_key = models.TextField(
        help_text='PEM-encoded public key for challenge-response verification',
    )

    platform = models.CharField(
        max_length=20,
        choices=DevicePlatform.choices,
        default=DevicePlatform.UNKNOWN,
    )

    device_name = models.CharField(max_length=255, blank=True)
    os_version = models.CharField(max_length=50, blank=True)

    status = models.CharField(
        max_length=20,
        choices=DeviceStatus.choices,
        default=DeviceStatus.ACTIVE,
    )

    registered_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    # Tracks whether the biometric configuration changed since registration.
    biometric_invalidated = models.BooleanField(default=False)

    # False when the device had no biometric hardware / no enrolled biometrics at
    # registration time. The RSA challenge-sign flow still runs; the local biometric
    # prompt is skipped on check-in for these devices.
    biometric_enrolled = models.BooleanField(
        default=True,
        help_text='False when the device registered without biometric hardware or enrolled biometrics.',
    )

    class Meta:
        db_table = 'devices'
        indexes = [
            models.Index(fields=['student', 'status']),
            models.Index(fields=['organization', 'status']),
        ]

    def __str__(self):
        return f'{self.device_name or self.device_fingerprint[:16]} ({self.status})'
