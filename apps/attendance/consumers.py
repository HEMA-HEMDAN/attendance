"""
WebSocket consumer for live attendance monitoring and snapshot location updates.

Teachers connect to a session channel to receive real-time attendance & location snapshot events.
Students do NOT connect here for continuous tracking — they use the REST API for check-in.

Channel group: "session_{session_id}"
"""

import json
import logging
from django.utils import timezone
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

from apps.accounts.models import Role

logger = logging.getLogger(__name__)


class AttendanceSessionConsumer(AsyncWebsocketConsumer):
    """
    Authenticated WebSocket consumer for live attendance monitoring.
    Scoped access: Doctor (owned course), TA (assigned group), Admin (org), Superadmin (platform).
    """

    async def connect(self):
        user = self.scope.get('user')
        session_id = self.scope['url_route']['kwargs']['session_id']

        if not user or not getattr(user, 'is_authenticated', False):
            await self.close(code=4001)
            return

        authorized = await self._is_authorized(user, session_id)
        if not authorized:
            await self.close(code=4003)
            return

        self.session_id = session_id
        self.group_name = f'session_{session_id}'

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Send initial connection metadata
        await self.send(text_data=json.dumps({
            'type': 'connection.state',
            'state': 'CONNECTED',
            'session_id': session_id,
            'timestamp': timezone.now().isoformat(),
        }))

        logger.info('WS connected: user=%s session=%s', user.id, session_id)

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        pass

    async def attendance_update(self, event):
        """Broadcast attendance record update and location snapshot to connected staff."""
        record = event['record']
        radar_status = 'KNOWN'
        radius_meters = record.get('radius_meters', 50)
        if record.get('distance_from_location_meters') is not None and record.get('distance_from_location_meters') > radius_meters:
            radar_status = 'OUTSIDE'
        elif record.get('submitted_latitude') is None:
            radar_status = 'UNKNOWN'

        await self.send(text_data=json.dumps({
            'type': 'attendance.update',
            'record': record,
            'location_snapshot': {
                'status': radar_status,
                'latitude': record.get('submitted_latitude'),
                'longitude': record.get('submitted_longitude'),
                'accuracy': record.get('location_accuracy_meters'),
                'captured_at': record.get('verified_at'),
            },
            'timestamp': timezone.now().isoformat(),
        }))

    async def session_state_change(self, event):
        """Broadcast session state change (e.g. CLOSED)."""
        await self.send(text_data=json.dumps({
            'type': 'session.state',
            'status': event['status'],
            'timestamp': timezone.now().isoformat(),
        }))

    @database_sync_to_async
    def _is_authorized(self, user, session_id: int) -> bool:
        from apps.attendance.models import AttendanceSession
        try:
            session = AttendanceSession.objects.select_related(
                'occurrence__course_offering__doctor__user',
                'occurrence__group__teaching_assistant__user',
            ).get(pk=session_id)
        except AttendanceSession.DoesNotExist:
            return False

        if user.role == Role.SUPERADMIN:
            return True

        if user.organization_id != session.organization_id:
            return False

        if user.role == Role.ADMIN:
            return True

        occ = session.occurrence
        if user.role == Role.DOCTOR:
            return bool(occ.course_offering.doctor and occ.course_offering.doctor.user_id == user.id)

        if user.role == Role.TEACHING_ASSISTANT:
            return bool(occ.group and occ.group.teaching_assistant and occ.group.teaching_assistant.user_id == user.id)

        return False
