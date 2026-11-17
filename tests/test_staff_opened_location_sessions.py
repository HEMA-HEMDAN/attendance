import pytest
from datetime import timedelta
from django.utils import timezone
from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.attendance.models import (
    SessionOccurrence, SessionOccurrenceStatus, OccurrenceType,
    AttendanceSession, SessionStatus,
)
from apps.attendance.services import (
    open_occurrence_session, create_and_open_adhoc_session, update_attendance_session,
    ATTENDANCE_DEFAULT_RADIUS_METERS,
)
from apps.audit.models import AuditLog, AuditAction
from tests.factories import (
    DoctorUserFactory, TAUserFactory, StudentUserFactory, AdminUserFactory,
    OrganizationFactory, AcademicYearFactory, SemesterFactory, CourseFactory, CourseOfferingFactory,
    GroupFactory, ScheduleFactory, DoctorFactory, TeachingAssistantFactory,
)


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestStaffOpenedSessionPermissions:

    def test_doctor_can_open_scheduled_lecture(self, client):
        org = OrganizationFactory()
        year = AcademicYearFactory(organization=org)
        sem = SemesterFactory(organization=org, academic_year=year)
        course = CourseFactory(organization=org)
        doctor_user = DoctorUserFactory(organization=org)
        doctor = DoctorFactory(user=doctor_user, organization=org)
        offering = CourseOfferingFactory(course=course, academic_year=year, semester=sem, doctor=doctor)
        sched = ScheduleFactory(course_offering=offering, session_type='LECTURE')

        occ = SessionOccurrence.objects.create(
            schedule=sched,
            course_offering=offering,
            scheduled_date=timezone.now().date(),
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(hours=1),
            session_type='LECTURE',
            status=SessionOccurrenceStatus.SCHEDULED,
            occurrence_type=OccurrenceType.SCHEDULED,
        )

        client.force_authenticate(user=doctor_user)
        now = timezone.now()
        payload = {
            'latitude': 30.0444,
            'longitude': 31.2357,
            'location_accuracy_meters': 10.0,
            'location_captured_at': now.isoformat(),
        }

        resp = client.post(f'/api/v1/attendance/occurrences/{occ.id}/open/', payload, format='json')
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        data = resp.data

        assert data['opened_by'] == doctor_user.id
        assert data['opened_by_name'] == doctor_user.get_full_name()
        assert float(data['latitude']) == pytest.approx(30.0444)
        assert float(data['longitude']) == pytest.approx(31.2357)
        assert data['location_accuracy_meters'] == 10.0
        assert data['radius_meters'] == ATTENDANCE_DEFAULT_RADIUS_METERS
        assert data['occurrence_type'] == 'SCHEDULED'

        occ.refresh_from_db()
        assert occ.status == SessionOccurrenceStatus.ACTIVE
        assert AuditLog.objects.filter(action=AuditAction.SESSION_OPENED, target_id=str(data['id'])).exists()

    def test_ta_can_open_assigned_group_lab(self, client):
        org = OrganizationFactory()
        year = AcademicYearFactory(organization=org)
        sem = SemesterFactory(organization=org, academic_year=year)
        course = CourseFactory(organization=org)
        doctor_user = DoctorUserFactory(organization=org)
        doctor = DoctorFactory(user=doctor_user, organization=org)
        offering = CourseOfferingFactory(course=course, academic_year=year, semester=sem, doctor=doctor)

        ta_user = TAUserFactory(organization=org)
        ta = TeachingAssistantFactory(user=ta_user, organization=org)
        group = GroupFactory(course_offering=offering, teaching_assistant=ta)

        sched = ScheduleFactory(course_offering=offering, group=group, session_type='LAB')
        occ = SessionOccurrence.objects.create(
            schedule=sched,
            course_offering=offering,
            group=group,
            scheduled_date=timezone.now().date(),
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(hours=1),
            session_type='LAB',
            status=SessionOccurrenceStatus.SCHEDULED,
            occurrence_type=OccurrenceType.SCHEDULED,
        )

        client.force_authenticate(user=ta_user)
        now = timezone.now()
        payload = {
            'latitude': 30.0500,
            'longitude': 31.2400,
            'location_accuracy_meters': 12.0,
            'location_captured_at': now.isoformat(),
        }

        resp = client.post(f'/api/v1/attendance/occurrences/{occ.id}/open/', payload, format='json')
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data['opened_by'] == ta_user.id

    def test_unauthorized_roles_cannot_open_session(self, client):
        org = OrganizationFactory()
        year = AcademicYearFactory(organization=org)
        sem = SemesterFactory(organization=org, academic_year=year)
        course = CourseFactory(organization=org)
        offering = CourseOfferingFactory(course=course, academic_year=year, semester=sem)
        sched = ScheduleFactory(course_offering=offering, session_type='LECTURE')
        occ = SessionOccurrence.objects.create(
            schedule=sched,
            course_offering=offering,
            scheduled_date=timezone.now().date(),
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(hours=1),
            session_type='LECTURE',
            status=SessionOccurrenceStatus.SCHEDULED,
            occurrence_type=OccurrenceType.SCHEDULED,
        )

        payload = {
            'latitude': 30.0444,
            'longitude': 31.2357,
            'location_accuracy_meters': 10.0,
            'location_captured_at': timezone.now().isoformat(),
        }

        # Student
        student_user = StudentUserFactory(organization=org)
        client.force_authenticate(user=student_user)
        resp = client.post(f'/api/v1/attendance/occurrences/{occ.id}/open/', payload, format='json')
        assert resp.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_400_BAD_REQUEST]

        # Admin
        admin_user = AdminUserFactory(organization=org)
        client.force_authenticate(user=admin_user)
        resp = client.post(f'/api/v1/attendance/occurrences/{occ.id}/open/', payload, format='json')
        assert resp.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_400_BAD_REQUEST]

        # SuperAdmin
        superadmin_user = AdminUserFactory(is_superuser=True, role=Role.SUPERADMIN)
        client.force_authenticate(user=superadmin_user)
        resp = client.post(f'/api/v1/attendance/occurrences/{occ.id}/open/', payload, format='json')
        assert resp.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_400_BAD_REQUEST]

    def test_doctor_scope_unowned_course_rejected(self, client):
        org = OrganizationFactory()
        year = AcademicYearFactory(organization=org)
        sem = SemesterFactory(organization=org, academic_year=year)
        course = CourseFactory(organization=org)

        doc1_user = DoctorUserFactory(organization=org)
        doc1 = DoctorFactory(user=doc1_user, organization=org)

        doc2_user = DoctorUserFactory(organization=org)

        offering = CourseOfferingFactory(course=course, academic_year=year, semester=sem, doctor=doc1)
        sched = ScheduleFactory(course_offering=offering, session_type='LECTURE')
        occ = SessionOccurrence.objects.create(
            schedule=sched,
            course_offering=offering,
            scheduled_date=timezone.now().date(),
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(hours=1),
            session_type='LECTURE',
            status=SessionOccurrenceStatus.SCHEDULED,
            occurrence_type=OccurrenceType.SCHEDULED,
        )

        client.force_authenticate(user=doc2_user)
        payload = {
            'latitude': 30.0444,
            'longitude': 31.2357,
            'location_accuracy_meters': 10.0,
            'location_captured_at': timezone.now().isoformat(),
        }

        resp = client.post(f'/api/v1/attendance/occurrences/{occ.id}/open/', payload, format='json')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['code'] == 'COURSE_NOT_IN_SCOPE'

    def test_ta_scope_unassigned_group_and_lecture_rejected(self, client):
        org = OrganizationFactory()
        year = AcademicYearFactory(organization=org)
        sem = SemesterFactory(organization=org, academic_year=year)
        course = CourseFactory(organization=org)
        offering = CourseOfferingFactory(course=course, academic_year=year, semester=sem)

        ta1_user = TAUserFactory(organization=org)
        ta1 = TeachingAssistantFactory(user=ta1_user, organization=org)
        group1 = GroupFactory(course_offering=offering, teaching_assistant=ta1)

        ta2_user = TAUserFactory(organization=org)

        sched = ScheduleFactory(course_offering=offering, group=group1, session_type='LAB')
        occ = SessionOccurrence.objects.create(
            schedule=sched,
            course_offering=offering,
            group=group1,
            scheduled_date=timezone.now().date(),
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(hours=1),
            session_type='LAB',
            status=SessionOccurrenceStatus.SCHEDULED,
            occurrence_type=OccurrenceType.SCHEDULED,
        )

        client.force_authenticate(user=ta2_user)
        payload = {
            'latitude': 30.0444,
            'longitude': 31.2357,
            'location_accuracy_meters': 10.0,
            'location_captured_at': timezone.now().isoformat(),
        }

        # Unassigned TA -> rejected
        resp = client.post(f'/api/v1/attendance/occurrences/{occ.id}/open/', payload, format='json')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['code'] == 'GROUP_NOT_IN_SCOPE'

        # TA attempting LECTURE -> rejected
        sched_lec = ScheduleFactory(course_offering=offering, group=group1, session_type='LECTURE')
        occ_lec = SessionOccurrence.objects.create(
            schedule=sched_lec,
            course_offering=offering,
            group=group1,
            scheduled_date=timezone.now().date(),
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(hours=1),
            session_type='LECTURE',
            status=SessionOccurrenceStatus.SCHEDULED,
            occurrence_type=OccurrenceType.SCHEDULED,
        )
        client.force_authenticate(user=ta1_user)
        resp = client.post(f'/api/v1/attendance/occurrences/{occ_lec.id}/open/', payload, format='json')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['code'] == 'INVALID_SESSION_TYPE'


@pytest.mark.django_db
class TestAdHocSessionStart:

    def test_doctor_creates_and_opens_adhoc_session(self, client):
        org = OrganizationFactory()
        year = AcademicYearFactory(organization=org)
        sem = SemesterFactory(organization=org, academic_year=year)
        course = CourseFactory(organization=org)
        doctor_user = DoctorUserFactory(organization=org)
        doctor = DoctorFactory(user=doctor_user, organization=org)
        offering = CourseOfferingFactory(course=course, academic_year=year, semester=sem, doctor=doctor)

        client.force_authenticate(user=doctor_user)
        now = timezone.now()
        payload = {
            'course_offering_id': offering.id,
            'session_type': 'LECTURE',
            'latitude': 30.0444,
            'longitude': 31.2357,
            'accuracy_m': 8.0,
            'location_captured_at': now.isoformat(),
        }

        resp = client.post('/api/v1/attendance/occurrences/ad-hoc/start/', payload, format='json')
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        data = resp.data

        assert data['opened_by'] == doctor_user.id
        assert data['occurrence_type'] == 'AD_HOC'
        assert data['radius_meters'] == ATTENDANCE_DEFAULT_RADIUS_METERS

        occ = SessionOccurrence.objects.get(pk=data['occurrence_id'])
        assert occ.occurrence_type == OccurrenceType.AD_HOC
        assert occ.schedule is None
        assert occ.status == SessionOccurrenceStatus.ACTIVE

        assert AuditLog.objects.filter(action=AuditAction.SESSION_CREATED, target_id=str(occ.id)).exists()
        assert AuditLog.objects.filter(action=AuditAction.SESSION_OPENED, target_id=str(data['id'])).exists()

    def test_server_controlled_radius_ignores_client_tampering(self, client):
        org = OrganizationFactory()
        year = AcademicYearFactory(organization=org)
        sem = SemesterFactory(organization=org, academic_year=year)
        course = CourseFactory(organization=org)
        doctor_user = DoctorUserFactory(organization=org)
        doctor = DoctorFactory(user=doctor_user, organization=org)
        offering = CourseOfferingFactory(course=course, academic_year=year, semester=sem, doctor=doctor)

        client.force_authenticate(user=doctor_user)
        now = timezone.now()
        payload = {
            'course_offering_id': offering.id,
            'session_type': 'LECTURE',
            'latitude': 30.0444,
            'longitude': 31.2357,
            'accuracy_m': 5.0,
            'location_captured_at': now.isoformat(),
            'radius_meters': 10000.0,  # Client tampering attempt
        }

        resp = client.post('/api/v1/attendance/occurrences/ad-hoc/start/', payload, format='json')
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data['radius_meters'] == 200.0

    def test_adhoc_transaction_rollback_on_location_failure(self, client):
        org = OrganizationFactory()
        year = AcademicYearFactory(organization=org)
        sem = SemesterFactory(organization=org, academic_year=year)
        course = CourseFactory(organization=org)
        doctor_user = DoctorUserFactory(organization=org)
        doctor = DoctorFactory(user=doctor_user, organization=org)
        offering = CourseOfferingFactory(course=course, academic_year=year, semester=sem, doctor=doctor)

        client.force_authenticate(user=doctor_user)
        initial_occ_count = SessionOccurrence.objects.count()

        payload = {
            'course_offering_id': offering.id,
            'session_type': 'LECTURE',
            'latitude': 30.0444,
            'longitude': 31.2357,
            'accuracy_m': 999.0,  # Unsafe accuracy -> location validation fails
            'location_captured_at': timezone.now().isoformat(),
        }

        resp = client.post('/api/v1/attendance/occurrences/ad-hoc/start/', payload, format='json')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['code'] == 'SESSION_LOCATION_ACCURACY_INVALID'

        # Transaction rollback invariant: No orphaned occurrence created
        assert SessionOccurrence.objects.count() == initial_occ_count


@pytest.mark.django_db
class TestLocationValidationAndImmutability:

    def test_missing_and_invalid_coordinates(self, client):
        org = OrganizationFactory()
        doctor_user = DoctorUserFactory(organization=org)
        doctor = DoctorFactory(user=doctor_user, organization=org)
        year = AcademicYearFactory(organization=org)
        sem = SemesterFactory(organization=org, academic_year=year)
        course = CourseFactory(organization=org)
        offering = CourseOfferingFactory(course=course, academic_year=year, semester=sem, doctor=doctor)
        sched = ScheduleFactory(course_offering=offering, session_type='LECTURE')
        occ = SessionOccurrence.objects.create(
            schedule=sched,
            course_offering=offering,
            scheduled_date=timezone.now().date(),
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(hours=1),
            session_type='LECTURE',
            status=SessionOccurrenceStatus.SCHEDULED,
        )

        client.force_authenticate(user=doctor_user)
        now = timezone.now()

        # Missing coords
        resp = client.post(f'/api/v1/attendance/occurrences/{occ.id}/open/', {
            'location_accuracy_meters': 10.0,
            'location_captured_at': now.isoformat(),
        }, format='json')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['code'] == 'SESSION_LOCATION_REQUIRED'

        # Invalid lat
        resp = client.post(f'/api/v1/attendance/occurrences/{occ.id}/open/', {
            'latitude': 999.0,
            'longitude': 31.0,
            'location_accuracy_meters': 10.0,
            'location_captured_at': now.isoformat(),
        }, format='json')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['code'] == 'SESSION_LOCATION_INVALID'

    def test_stale_and_future_timestamp_rejected(self, client):
        org = OrganizationFactory()
        doctor_user = DoctorUserFactory(organization=org)
        doctor = DoctorFactory(user=doctor_user, organization=org)
        year = AcademicYearFactory(organization=org)
        sem = SemesterFactory(organization=org, academic_year=year)
        course = CourseFactory(organization=org)
        offering = CourseOfferingFactory(course=course, academic_year=year, semester=sem, doctor=doctor)
        sched = ScheduleFactory(course_offering=offering, session_type='LECTURE')
        occ = SessionOccurrence.objects.create(
            schedule=sched,
            course_offering=offering,
            scheduled_date=timezone.now().date(),
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(hours=1),
            session_type='LECTURE',
            status=SessionOccurrenceStatus.SCHEDULED,
        )

        client.force_authenticate(user=doctor_user)

        # Stale timestamp (10 minutes old)
        stale_time = timezone.now() - timedelta(minutes=10)
        resp = client.post(f'/api/v1/attendance/occurrences/{occ.id}/open/', {
            'latitude': 30.0,
            'longitude': 31.0,
            'location_accuracy_meters': 10.0,
            'location_captured_at': stale_time.isoformat(),
        }, format='json')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['code'] == 'SESSION_LOCATION_STALE'

        # Future timestamp (5 minutes in future)
        future_time = timezone.now() + timedelta(minutes=5)
        resp = client.post(f'/api/v1/attendance/occurrences/{occ.id}/open/', {
            'latitude': 30.0,
            'longitude': 31.0,
            'location_accuracy_meters': 10.0,
            'location_captured_at': future_time.isoformat(),
        }, format='json')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['code'] == 'SESSION_LOCATION_STALE'

    def test_active_session_opening_metadata_immutable(self, client):
        org = OrganizationFactory()
        doctor_user = DoctorUserFactory(organization=org)
        doctor = DoctorFactory(user=doctor_user, organization=org)
        year = AcademicYearFactory(organization=org)
        sem = SemesterFactory(organization=org, academic_year=year)
        course = CourseFactory(organization=org)
        offering = CourseOfferingFactory(course=course, academic_year=year, semester=sem, doctor=doctor)
        sched = ScheduleFactory(course_offering=offering, session_type='LECTURE')
        occ = SessionOccurrence.objects.create(
            schedule=sched,
            course_offering=offering,
            scheduled_date=timezone.now().date(),
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(hours=1),
            session_type='LECTURE',
            status=SessionOccurrenceStatus.SCHEDULED,
        )

        now = timezone.now()
        session = open_occurrence_session(
            user=doctor_user,
            occurrence_id=occ.id,
            latitude=30.0444,
            longitude=31.2357,
            location_accuracy_meters=10.0,
            location_captured_at=now,
        )

        assert session.status == SessionStatus.ACTIVE

        # Attempt to mutate latitude/longitude on active session via update service
        with pytest.raises(ValueError) as exc:
            update_attendance_session(session, latitude=35.0000)
        assert exc.value.args[1] == 'SESSION_LOCATION_IMMUTABLE'


@pytest.mark.django_db
class TestOccurrenceModelInvariants:

    def test_scheduled_occurrence_requires_schedule(self):
        org = OrganizationFactory()
        year = AcademicYearFactory(organization=org)
        sem = SemesterFactory(organization=org, academic_year=year)
        course = CourseFactory(organization=org)
        offering = CourseOfferingFactory(course=course, academic_year=year, semester=sem)

        occ = SessionOccurrence(
            occurrence_type=OccurrenceType.SCHEDULED,
            schedule=None,  # Invalid
            course_offering=offering,
            scheduled_date=timezone.now().date(),
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(hours=1),
            session_type='LECTURE',
        )

        with pytest.raises(ValidationError) as exc:
            occ.clean()
        assert 'schedule' in exc.value.message_dict

    def test_adhoc_occurrence_must_have_no_schedule(self):
        org = OrganizationFactory()
        year = AcademicYearFactory(organization=org)
        sem = SemesterFactory(organization=org, academic_year=year)
        course = CourseFactory(organization=org)
        offering = CourseOfferingFactory(course=course, academic_year=year, semester=sem)
        sched = ScheduleFactory(course_offering=offering)

        occ = SessionOccurrence(
            occurrence_type=OccurrenceType.AD_HOC,
            schedule=sched,  # Invalid
            course_offering=offering,
            scheduled_date=timezone.now().date(),
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(hours=1),
            session_type='LECTURE',
        )

        with pytest.raises(ValidationError) as exc:
            occ.clean()
        assert 'schedule' in exc.value.message_dict
