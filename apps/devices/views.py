from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone
from django.db.models import Q

from apps.accounts.permissions import IsStudent, IsOrganizationAdmin, IsAdmin
from apps.audit.service import audit
from apps.audit.models import AuditAction

from .models import Device
from .serializers import DeviceRegistrationSerializer, DeviceSerializer


class DeviceRegisterView(generics.CreateAPIView):
    """Student registers a device."""
    permission_classes = [IsStudent]
    serializer_class = DeviceRegistrationSerializer

    def create(self, request, *args, **kwargs):
        student = request.user.student_profile
        
        # Check if student has an active session for an enrolled course offering or group
        from apps.attendance.models import AttendanceSession, SessionStatus

        enrollments = student.enrollments.all()
        offering_ids = [e.course_offering_id for e in enrollments]
        group_ids = [e.group_id for e in enrollments if e.group_id]

        has_active = AttendanceSession.objects.filter(
            organization=student.organization,
            status=SessionStatus.ACTIVE
        ).filter(
            Q(occurrence__course_offering_id__in=offering_ids, occurrence__group__isnull=True) |
            Q(occurrence__group_id__in=group_ids)
        ).exists()

        if has_active:
            return Response(
                {
                    'detail': 'Device registration is locked while an active attendance session is in progress for your enrolled course/group.',
                    'code': 'DEVICE_REGISTRATION_LOCKED_ACTIVE_SESSION',
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        device = serializer.save()
        audit(
            action=AuditAction.DEVICE_REGISTERED,
            actor=request.user,
            organization=request.user.organization,
            target_type='Device',
            target_id=device.id,
            metadata={
                'platform': device.platform,
                'device_name': device.device_name,
            },
        )
        return Response(DeviceSerializer(device).data, status=status.HTTP_201_CREATED)


class DeviceListView(generics.ListAPIView):
    """Student views their own registered devices."""
    permission_classes = [IsStudent]
    serializer_class = DeviceSerializer

    def get_queryset(self):
        student = getattr(self.request.user, 'student_profile', None)
        if not student:
            return Device.objects.none()
        return Device.objects.filter(
            student=student
        ).order_by('-registered_at')


class AdminDeviceListView(generics.ListAPIView):
    """Admin views all devices for their organization."""
    permission_classes = [IsOrganizationAdmin]
    serializer_class = DeviceSerializer

    def get_queryset(self):
        qs = Device.objects.filter(
            organization=self.request.user.organization
        ).select_related('student__user').order_by('-registered_at')

        student_id = self.request.query_params.get('student')
        if student_id:
            qs = qs.filter(student_id=student_id)

        return qs


class AdminDeviceRevokeView(APIView):
    """Organization Admin or Superadmin revokes a device. Students CANNOT self-revoke."""
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        try:
            device = Device.objects.get(
                pk=pk,
                organization=request.user.organization,
                status='ACTIVE',
            )
        except Device.DoesNotExist:
            return Response({'detail': 'Device not found'}, status=status.HTTP_404_NOT_FOUND)

        device.status = 'REVOKED'
        device.revoked_at = timezone.now()
        device.save()

        audit(
            action=AuditAction.DEVICE_REVOKED,
            actor=request.user,
            organization=request.user.organization,
            target_type='Device',
            target_id=device.id,
        )

        return Response({'detail': 'Device revoked successfully'})
