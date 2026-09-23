"""
WebSocket Authorization & Scope Hardening Tests.
"""

import pytest
from channels.testing import WebsocketCommunicator

from apps.accounts.models import Role, User
from apps.attendance.consumers import AttendanceSessionConsumer
from apps.attendance.models import SessionStatus

from tests.factories import (
    OrganizationFactory, AdminUserFactory, DoctorUserFactory, TAUserFactory,
    DoctorFactory, TeachingAssistantFactory, StudentUserFactory, CourseFactory,
    CourseOfferingFactory, GroupFactory, ScheduleFactory, SessionOccurrenceFactory,
    AttendanceSessionFactory,
)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestWebSocketAuthorization:
    async def test_unauthenticated_connection_rejected(self):
        communicator = WebsocketCommunicator(
            AttendanceSessionConsumer.as_asgi(),
            "/ws/attendance/session/1/"
        )
        communicator.scope['user'] = None
        communicator.scope['url_route'] = {'kwargs': {'session_id': 1}}

        connected, close_code = await communicator.connect()
        assert not connected
        assert close_code == 4001

    async def test_authorized_doctor_connection_accepted(self):
        org = await database_sync_to_async_fn(OrganizationFactory)()
        doc_user = await database_sync_to_async_fn(DoctorUserFactory)(organization=org)
        doc = await database_sync_to_async_fn(DoctorFactory)(user=doc_user)

        course = await database_sync_to_async_fn(CourseFactory)(organization=org)
        offering = await database_sync_to_async_fn(CourseOfferingFactory)(course=course, doctor=doc)
        schedule = await database_sync_to_async_fn(ScheduleFactory)(course_offering=offering)
        occurrence = await database_sync_to_async_fn(SessionOccurrenceFactory)(schedule=schedule, course_offering=offering)
        session = await database_sync_to_async_fn(AttendanceSessionFactory)(occurrence=occurrence, organization=org)

        communicator = WebsocketCommunicator(
            AttendanceSessionConsumer.as_asgi(),
            f"/ws/attendance/session/{session.id}/"
        )
        communicator.scope['user'] = doc_user
        communicator.scope['url_route'] = {'kwargs': {'session_id': session.id}}

        connected, subprotocol = await communicator.connect()
        assert connected
        await communicator.disconnect()

    async def test_unauthorized_doctor_connection_rejected(self):
        org = await database_sync_to_async_fn(OrganizationFactory)()
        doc_user1 = await database_sync_to_async_fn(DoctorUserFactory)(organization=org)
        await database_sync_to_async_fn(DoctorFactory)(user=doc_user1)

        doc2 = await database_sync_to_async_fn(DoctorFactory)(user__organization=org)

        course = await database_sync_to_async_fn(CourseFactory)(organization=org)
        offering = await database_sync_to_async_fn(CourseOfferingFactory)(course=course, doctor=doc2)
        schedule = await database_sync_to_async_fn(ScheduleFactory)(course_offering=offering)
        occurrence = await database_sync_to_async_fn(SessionOccurrenceFactory)(schedule=schedule, course_offering=offering)
        session = await database_sync_to_async_fn(AttendanceSessionFactory)(occurrence=occurrence, organization=org)

        communicator = WebsocketCommunicator(
            AttendanceSessionConsumer.as_asgi(),
            f"/ws/attendance/session/{session.id}/"
        )
        communicator.scope['user'] = doc_user1
        communicator.scope['url_route'] = {'kwargs': {'session_id': session.id}}

        connected, close_code = await communicator.connect()
        assert not connected
        assert close_code == 4003


def database_sync_to_async_fn(factory_cls):
    from channels.db import database_sync_to_async
    return database_sync_to_async(factory_cls.create)
