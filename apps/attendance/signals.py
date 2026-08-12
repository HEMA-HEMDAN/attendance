"""
Signal to broadcast attendance record via WebSocket after successful check-in.
Called from AttendanceVerificationService after record creation.
"""

import json
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def broadcast_attendance_record(record):
    """
    Broadcast an attendance record to the session's WebSocket group.
    Non-blocking — failures are logged but don't affect the check-in response.
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        channel_layer = get_channel_layer()
        group_name = f'session_{record.session_id}'

        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': 'attendance.update',
                'record': {
                    'id': record.id,
                    'student_id': record.student.student_id,
                    'student_name': record.student.user.get_full_name(),
                    'status': record.status,
                    'verified_at': record.verified_at.isoformat(),
                    'distance_from_location_meters': record.distance_from_location_meters,
                    'submitted_latitude': float(record.submitted_latitude) if record.submitted_latitude else None,
                    'submitted_longitude': float(record.submitted_longitude) if record.submitted_longitude else None,
                },
            }
        )
    except Exception as exc:
        logger.warning('WebSocket broadcast failed: %s', exc)
