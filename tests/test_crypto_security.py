"""
Cross-Platform Cryptographic & Biometric Contract Security Tests.
Verifies platform-neutral challenge token issuance, RSA signature verification,
replay protection, TTL expiration, and proof enforcement.
"""

import pytest
import base64
from datetime import timedelta
from django.utils import timezone
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization

from apps.attendance.models import DeviceChallenge, SessionStatus
from apps.attendance.verification import AttendanceVerificationService, VerificationError
from apps.devices.models import Device

from tests.factories import (
    OrganizationFactory, DoctorUserFactory, DoctorFactory, StudentUserFactory,
    StudentFactory, CourseOfferingFactory, GroupFactory, StudentEnrollmentFactory,
    ScheduleFactory, SessionOccurrenceFactory, AttendanceSessionFactory,
)


def generate_rsa_key_pair():
    """Generate a real 2048-bit RSA key pair for testing signature verification."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')
    return private_key, public_key_pem


def sign_challenge(private_key, challenge_token: str) -> str:
    """Sign a challenge token string with private key and return base64 signature."""
    signature = private_key.sign(
        challenge_token.encode('utf-8'),
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')


@pytest.mark.django_db
class TestCryptographicSecurityContract:
    def test_valid_rsa_signature_verification_succeeds(self):
        org = OrganizationFactory()
        student_user = StudentUserFactory(organization=org)
        student = StudentFactory(user=student_user)

        offering = CourseOfferingFactory(course__organization=org)
        group = GroupFactory(course_offering=offering)
        StudentEnrollmentFactory(student=student, course_offering=offering, group=group)

        schedule = ScheduleFactory(course_offering=offering, group=group, session_type='LAB')
        occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=offering, group=group)
        session = AttendanceSessionFactory(occurrence=occurrence, organization=org, status=SessionStatus.ACTIVE)

        private_key, public_key_pem = generate_rsa_key_pair()

        device = Device.objects.create(
            student=student,
            organization=org,
            device_fingerprint='test_fp_key',
            public_key=public_key_pem,
            status='ACTIVE',
        )

        svc = AttendanceVerificationService(student)
        challenge = svc.issue_challenge(device_id=device.id, session_id=session.id)

        signature_b64 = sign_challenge(private_key, challenge.challenge_token)

        # Full verification
        record = svc.verify(
            session_id=session.id,
            device_id=device.id,
            challenge_token=challenge.challenge_token,
            signature_b64=signature_b64,
            latitude=float(session.latitude),
            longitude=float(session.longitude),
            location_accuracy=10.0,
            location_timestamp=timezone.now().timestamp(),
        )

        assert record.id is not None
        assert record.device_challenge_verified is True
        challenge.refresh_from_db()
        assert challenge.is_used is True

    def test_invalid_signature_rejected(self):
        org = OrganizationFactory()
        student_user = StudentUserFactory(organization=org)
        student = StudentFactory(user=student_user)

        offering = CourseOfferingFactory(course__organization=org)
        group = GroupFactory(course_offering=offering)
        StudentEnrollmentFactory(student=student, course_offering=offering, group=group)

        schedule = ScheduleFactory(course_offering=offering, group=group)
        occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=offering, group=group)
        session = AttendanceSessionFactory(occurrence=occurrence, organization=org, status=SessionStatus.ACTIVE)

        private_key, public_key_pem = generate_rsa_key_pair()
        wrong_private_key, _ = generate_rsa_key_pair()

        device = Device.objects.create(
            student=student,
            organization=org,
            device_fingerprint='test_fp_key',
            public_key=public_key_pem,
            status='ACTIVE',
        )

        svc = AttendanceVerificationService(student)
        challenge = svc.issue_challenge(device_id=device.id, session_id=session.id)

        bad_signature_b64 = sign_challenge(wrong_private_key, challenge.challenge_token)

        with pytest.raises(VerificationError) as exc_info:
            svc.verify(
                session_id=session.id,
                device_id=device.id,
                challenge_token=challenge.challenge_token,
                signature_b64=bad_signature_b64,
                latitude=float(session.latitude),
                longitude=float(session.longitude),
            )
        assert exc_info.value.code == 'SIGNATURE_INVALID'

    def test_challenge_replay_rejected(self):
        org = OrganizationFactory()
        student_user = StudentUserFactory(organization=org)
        student = StudentFactory(user=student_user)

        offering = CourseOfferingFactory(course__organization=org)
        group = GroupFactory(course_offering=offering)
        StudentEnrollmentFactory(student=student, course_offering=offering, group=group)

        schedule = ScheduleFactory(course_offering=offering, group=group)
        occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=offering, group=group)
        session = AttendanceSessionFactory(occurrence=occurrence, organization=org, status=SessionStatus.ACTIVE)

        private_key, public_key_pem = generate_rsa_key_pair()
        device = Device.objects.create(
            student=student, organization=org, device_fingerprint='fp', public_key=public_key_pem, status='ACTIVE',
        )

        svc = AttendanceVerificationService(student)
        challenge = svc.issue_challenge(device_id=device.id, session_id=session.id)
        signature_b64 = sign_challenge(private_key, challenge.challenge_token)

        svc.verify(
            session_id=session.id, device_id=device.id, challenge_token=challenge.challenge_token,
            signature_b64=signature_b64, latitude=float(session.latitude), longitude=float(session.longitude),
        )

        # Attempt replay with same challenge token
        with pytest.raises(VerificationError) as exc_info:
            svc.verify(
                session_id=session.id, device_id=device.id, challenge_token=challenge.challenge_token,
                signature_b64=signature_b64, latitude=float(session.latitude), longitude=float(session.longitude),
            )
        assert exc_info.value.code in ('CHALLENGE_EXPIRED', 'DUPLICATE_ATTENDANCE')

    def test_issuing_new_challenge_invalidates_old_unused_challenge(self):
        org = OrganizationFactory()
        student_user = StudentUserFactory(organization=org)
        student = StudentFactory(user=student_user)

        offering = CourseOfferingFactory(course__organization=org)
        schedule = ScheduleFactory(course_offering=offering)
        occurrence = SessionOccurrenceFactory(schedule=schedule, course_offering=offering)
        session = AttendanceSessionFactory(occurrence=occurrence, organization=org, status=SessionStatus.ACTIVE)

        _, public_key_pem = generate_rsa_key_pair()
        device = Device.objects.create(student=student, organization=org, device_fingerprint='fp', public_key=public_key_pem, status='ACTIVE')

        svc = AttendanceVerificationService(student)
        c1 = svc.issue_challenge(device_id=device.id, session_id=session.id)
        c2 = svc.issue_challenge(device_id=device.id, session_id=session.id)

        c1.refresh_from_db()
        c2.refresh_from_db()

        assert c1.is_used is True
        assert c2.is_used is False
