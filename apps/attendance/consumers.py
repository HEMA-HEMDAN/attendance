"""
WebSocket consumer for live attendance monitoring.

Teachers connect to a session channel to receive real-time attendance updates.
Students do NOT connect here — they use the REST API for check-in.

Channel group: "session_{session_id}"

Events published when a student checks in:
  {
    "type": "attendance.update",
    "record": { ... }
  }
"""

import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

logger = logging.getLogger(__name__)


class AttendanceSessionConsumer(AsyncWebsocketConsumer):
    """
    Authenticated WebSocket consumer for live attendance monitoring.
    Only teachers assigned to the session (or org admins) may connect.
    """

    async def connect(self):
        user = self.scope.get('user')
        session_id = self.scope['url_route']['kwargs']['session_id']

        # Reject unauthenticated connections
        if not user or not getattr(user, 'is_authenticated', False):
            await self.close(code=4001)
            return

        # Authorization check
        authorized = await self._is_authorized(user, session_id)
        if not authorized:
            await self.close(code=4003)
            return

        self.session_id = session_id
        self.group_name = f'session_{session_id}'

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        logger.info('WS connected: user=%s session=%s', user.id, session_id)

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        # Teacher-side consumer is receive-only (no client→server messages in MVP)
        pass

    async def attendance_update(self, event):
        """Broadcast attendance update to connected clients."""
        await self.send(text_data=json.dumps({
            'type': 'attendance.update',
            'record': event['record'],
        }))

    @database_sync_to_async
    def _is_authorized(self, user, session_id: int) -> bool:
        from apps.attendance.models import AttendanceSession
        try:
            session = AttendanceSession.objects.select_related('teacher__user').get(pk=session_id)
        except AttendanceSession.DoesNotExist:
            return False

        if user.organization_id != session.organization_id:
            return False

        if user.role == 'ADMIN':
            return True

        if user.role in ['DOCTOR', 'TEACHING_ASSISTANT']:
            return session.teacher.user_id == user.id

        return False
