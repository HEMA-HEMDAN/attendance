"""Accounts views — authentication endpoints."""

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.audit.service import audit
from apps.audit.models import AuditAction
from .serializers import CustomTokenObtainPairSerializer, UserSerializer, ChangePasswordSerializer
from .models import User

from django.core.cache import cache
import secrets
import base64
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from apps.devices.models import Device


class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        device_fingerprint = request.data.get('device_fingerprint')
        if device_fingerprint:
            # Check if bound to another user
            email = request.data.get('email')
            user_qs = User.objects.filter(email=email)
            if user_qs.exists():
                user = user_qs.first()
                if hasattr(user, 'student_profile'):
                    other_active = Device.objects.filter(
                        device_fingerprint=device_fingerprint,
                        status='ACTIVE',
                    ).exclude(student=user.student_profile).first()
                    if other_active:
                        return Response({'detail': 'Device is bound to another user. Multi-account sharing is prohibited.'}, status=status.HTTP_403_FORBIDDEN)

        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            user = User.objects.filter(email=request.data.get('email')).first()
            if user:
                audit(
                    action=AuditAction.LOGIN_SUCCESS,
                    actor=user,
                    organization=user.organization,
                    ip_address=self._get_ip(request),
                )
        return response

    def _get_ip(self, request):
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded:
            return x_forwarded.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')


class LogoutView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
        except Exception:
            pass
        return Response({'detail': 'Logged out'}, status=status.HTTP_200_OK)


class MeView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class ChangePasswordView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save()
        return Response({'detail': 'Password changed'})

class DeviceLoginChallengeView(generics.GenericAPIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        device_fingerprint = request.data.get('device_fingerprint')
        if not device_fingerprint:
            return Response({'detail': 'device_fingerprint is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        device = Device.objects.filter(device_fingerprint=device_fingerprint, status='ACTIVE').first()
        if not device:
            return Response({'detail': 'Device not registered or revoked'}, status=status.HTTP_404_NOT_FOUND)

        challenge = secrets.token_hex(32)
        cache.set(f"device_login_{device_fingerprint}", challenge, timeout=120)
        
        return Response({'challenge': challenge})

class DeviceLoginVerifyView(generics.GenericAPIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        device_fingerprint = request.data.get('device_fingerprint')
        challenge = request.data.get('challenge')
        signature = request.data.get('signature')

        if not all([device_fingerprint, challenge, signature]):
            return Response({'detail': 'Missing parameters'}, status=status.HTTP_400_BAD_REQUEST)

        cached_challenge = cache.get(f"device_login_{device_fingerprint}")
        if not cached_challenge or cached_challenge != challenge:
            return Response({'detail': 'Challenge expired or invalid'}, status=status.HTTP_400_BAD_REQUEST)

        device = Device.objects.filter(device_fingerprint=device_fingerprint, status='ACTIVE').first()
        if not device:
            return Response({'detail': 'Device not found'}, status=status.HTTP_404_NOT_FOUND)

        try:
            public_key = load_pem_public_key(device.public_key.encode(), backend=default_backend())
            sig_bytes = base64.b64decode(signature)
            public_key.verify(
                sig_bytes,
                challenge.encode(),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
        except InvalidSignature:
            return Response({'detail': 'Invalid signature'}, status=status.HTTP_401_UNAUTHORIZED)
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Success, clear challenge
        cache.delete(f"device_login_{device_fingerprint}")

        user = device.student.user
        refresh = RefreshToken.for_user(user)
        
        audit(
            action=AuditAction.LOGIN_SUCCESS,
            actor=user,
            organization=user.organization,
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR'),
            metadata={'method': 'device_biometrics'}
        )

        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        })
