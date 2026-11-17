"""
Attendance domain services — today's work calculation, occurrence generation,
session opening, session closing.
"""

import zoneinfo
from datetime import datetime, time, timedelta
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.db.models import Q

from apps.accounts.models import Role
from apps.courses.models import AcademicYear, Semester, Schedule, ScheduleException, ExceptionType
from .models import SessionOccurrence, SessionOccurrenceStatus, AttendanceSession, SessionStatus, AttendanceRecord


def get_org_now_and_today(organization):
    """Return (current_dt_in_org_tz, today_date_in_org_tz, weekday_int) for organization."""
    tz_name = getattr(organization, 'timezone', 'Africa/Cairo') or 'Africa/Cairo'
    try:
        org_tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        org_tz = zoneinfo.ZoneInfo('Africa/Cairo')

    now_utc = timezone.now()
    org_now = now_utc.astimezone(org_tz)
    today_date = org_now.date()
    weekday_int = today_date.weekday()  # 0=Monday..6=Sunday
    return org_now, today_date, weekday_int


def sync_today_occurrences(organization):
    """
    Generate or sync SessionOccurrence records for today in the organization's timezone.
    """
    org_now, today_date, weekday_int = get_org_now_and_today(organization)

    # Find active AcademicYear and Semester
    active_years = AcademicYear.objects.filter(
        organization=organization,
        is_active=True,
        start_date__lte=today_date,
        end_date__gte=today_date,
    )
    if not active_years.exists():
        return []

    active_semesters = Semester.objects.filter(
        organization=organization,
        academic_year__in=active_years,
        is_active=True,
        start_date__lte=today_date,
        end_date__gte=today_date,
    )
    if not active_semesters.exists():
        return []

    # Find matching active schedules for today's weekday
    schedules = Schedule.objects.filter(
        course_offering__semester__in=active_semesters,
        course_offering__status='ACTIVE',
        day_of_week=weekday_int,
        is_active=True,
    ).select_related('course_offering__course', 'group')

    tz_name = getattr(organization, 'timezone', 'Africa/Cairo') or 'Africa/Cairo'
    try:
        org_tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        org_tz = zoneinfo.ZoneInfo('Africa/Cairo')

    occurrences = []
    for sched in schedules:
        # Check schedule date boundaries
        if sched.effective_from and today_date < sched.effective_from:
            continue
        if sched.effective_until and today_date > sched.effective_until:
            continue

        # Check schedule exception
        exception = ScheduleException.objects.filter(schedule=sched, date=today_date).first()
        if exception and exception.exception_type == ExceptionType.CANCELLED:
            continue

        # Calculate start and end datetimes in org timezone
        start_t = exception.new_start_time if (exception and exception.new_start_time) else sched.start_time
        end_t = exception.new_end_time if (exception and exception.new_end_time) else sched.end_time

        starts_dt = datetime.combine(today_date, start_t, tzinfo=org_tz)
        ends_dt = datetime.combine(today_date, end_t, tzinfo=org_tz)

        occ, _ = SessionOccurrence.objects.get_or_create(
            schedule=sched,
            scheduled_date=today_date,
            defaults={
                'course_offering': sched.course_offering,
                'group': sched.group,
                'starts_at': starts_dt,
                'ends_at': ends_dt,
                'session_type': sched.session_type,
                'status': SessionOccurrenceStatus.SCHEDULED,
            }
        )
        occurrences.append(occ)

    return occurrences


def filter_today_work_list(work_list, search=None, session_type=None, status=None):
    filtered = work_list
    if search:
        s = search.strip().lower()
        filtered = [
            w for w in filtered
            if s in (w.get('course_code') or '').lower()
            or s in (w.get('course_name') or '').lower()
            or s in (w.get('group_name') or '').lower()
        ]
    if session_type and session_type != 'ALL':
        filtered = [w for w in filtered if w.get('session_type') == session_type]
    if status and status != 'ALL':
        if status == 'OPEN':
            filtered = [w for w in filtered if w.get('session_status') in ['ACTIVE', 'SCHEDULED'] or w.get('can_open')]
        else:
            filtered = [w for w in filtered if w.get('session_status') == status]
    return filtered


def get_doctor_today_work(user, search=None, session_type=None, status=None):
    """
    Returns today's lecture occurrences and section details for a Doctor.
    """
    org = user.organization
    sync_today_occurrences(org)
    _, today_date, _ = get_org_now_and_today(org)

    # Doctor owns course offerings
    from apps.staff.models import Doctor
    doctor_profile = Doctor.objects.filter(user=user, organization=org).first()
    if not doctor_profile:
        return []

    offerings = doctor_profile.course_offerings.filter(status='ACTIVE').select_related('course')
    offering_ids = [o.id for o in offerings]

    occurrences = SessionOccurrence.objects.filter(
        course_offering_id__in=offering_ids,
        scheduled_date=today_date,
    ).select_related(
        'course_offering__course', 'group', 'attendance_session', 'schedule'
    ).order_by('starts_at')

    # Also prefetch section groups for owned courses
    from apps.groups.models import Group
    groups = Group.objects.filter(
        course_offering_id__in=offering_ids,
        status='ACTIVE',
    ).select_related('teaching_assistant__user')

    group_map = {}
    for g in groups:
        if g.course_offering_id not in group_map:
            group_map[g.course_offering_id] = []
        ta_name = g.teaching_assistant.user.get_full_name() if g.teaching_assistant else 'Unassigned'
        group_map[g.course_offering_id].append({
            'group_id': g.id,
            'group_name': g.name,
            'ta_name': ta_name,
        })

    result = []
    for occ in occurrences:
        att_session = getattr(occ, 'attendance_session', None)
        sess_status = att_session.status if att_session else 'SCHEDULED'
        sess_id = att_session.id if att_session else None

        can_open = (occ.session_type == 'LECTURE' and sess_status == 'SCHEDULED')
        can_close = (sess_status == 'ACTIVE')

        result.append({
            'occurrence_id': occ.id,
            'schedule_id': occ.schedule_id,
            'course_offering_id': occ.course_offering_id,
            'course_code': occ.course_offering.course.code,
            'course_name': occ.course_offering.course.name,
            'group_id': occ.group_id,
            'group_name': occ.group.name if occ.group else None,
            'session_type': occ.session_type,
            'scheduled_date': occ.scheduled_date,
            'starts_at': occ.starts_at,
            'ends_at': occ.ends_at,
            'session_id': sess_id,
            'session_status': sess_status,
            'can_open': can_open,
            'can_close': can_close,
            'sections': group_map.get(occ.course_offering_id, []),
        })

    return filter_today_work_list(result, search=search, session_type=session_type, status=status)


def get_ta_today_work(user, search=None, session_type=None, status=None):
    """
    Returns today's LAB and TUTORIAL occurrences for a Teaching Assistant's assigned groups.
    """
    org = user.organization
    sync_today_occurrences(org)
    _, today_date, _ = get_org_now_and_today(org)

    from apps.staff.models import TeachingAssistant
    ta_profile = TeachingAssistant.objects.filter(user=user, organization=org).first()
    if not ta_profile:
        return []

    assigned_groups = ta_profile.assigned_groups.filter(status='ACTIVE')
    group_ids = [g.id for g in assigned_groups]

    occurrences = SessionOccurrence.objects.filter(
        group_id__in=group_ids,
        scheduled_date=today_date,
        session_type__in=['LAB', 'TUTORIAL'],
    ).select_related(
        'course_offering__course', 'group', 'attendance_session', 'schedule'
    ).order_by('starts_at')

    result = []
    for occ in occurrences:
        att_session = getattr(occ, 'attendance_session', None)
        sess_status = att_session.status if att_session else 'SCHEDULED'
        sess_id = att_session.id if att_session else None

        can_open = (sess_status == 'SCHEDULED')
        can_close = (sess_status == 'ACTIVE')

        result.append({
            'occurrence_id': occ.id,
            'schedule_id': occ.schedule_id,
            'course_offering_id': occ.course_offering_id,
            'course_code': occ.course_offering.course.code,
            'course_name': occ.course_offering.course.name,
            'group_id': occ.group_id,
            'group_name': occ.group.name if occ.group else None,
            'session_type': occ.session_type,
            'scheduled_date': occ.scheduled_date,
            'starts_at': occ.starts_at,
            'ends_at': occ.ends_at,
            'session_id': sess_id,
            'session_status': sess_status,
            'can_open': can_open,
            'can_close': can_close,
        })

    return filter_today_work_list(result, search=search, session_type=session_type, status=status)


def get_student_today_work(user):
    """
    Returns today's active eligible attendance sessions for a student.
    """
    student = getattr(user, 'student_profile', None)
    if not student:
        return []

    enrollments = student.enrollments.all()
    offering_ids = [e.course_offering_id for e in enrollments]
    group_ids = [e.group_id for e in enrollments if e.group_id]

    now = timezone.now()
    active_sessions = AttendanceSession.objects.filter(
        organization=student.organization,
        status=SessionStatus.ACTIVE,
        expires_at__gt=now,
    ).filter(
        Q(occurrence__course_offering_id__in=offering_ids, occurrence__group__isnull=True) |
        Q(occurrence__group_id__in=group_ids)
    ).select_related('occurrence__course_offering__course', 'occurrence__group')

    checked_in_session_ids = set(
        AttendanceRecord.objects.filter(
            session__in=active_sessions,
            student=student,
        ).values_list('session_id', flat=True)
    )

    result = []
    for sess in active_sessions:
        occ = sess.occurrence
        result.append({
            'session_id': sess.id,
            'occurrence_id': occ.id,
            'course_code': occ.course_offering.course.code,
            'course_name': occ.course_offering.course.name,
            'group_name': occ.group.name if occ.group else None,
            'session_type': occ.session_type,
            'starts_at': sess.starts_at,
            'expires_at': sess.expires_at,
            'radius_meters': sess.radius_meters,
            'latitude': float(sess.latitude) if sess.latitude else None,
            'longitude': float(sess.longitude) if sess.longitude else None,
            'has_checked_in': sess.id in checked_in_session_ids,
        })

    return result


from apps.audit.service import audit
from apps.audit.models import AuditAction
from .models import SessionOccurrence, SessionOccurrenceStatus, OccurrenceType, AttendanceSession, SessionStatus, AttendanceRecord

ATTENDANCE_DEFAULT_RADIUS_METERS = 200.0
ATTENDANCE_MAX_LOCATION_ACCURACY_METERS = 200.0
ATTENDANCE_LOCATION_MAX_AGE_SECONDS = 300
ATTENDANCE_LOCATION_MAX_FUTURE_SKEW_SECONDS = 60


def get_organization_policy(organization):
    """
    Returns the OrganizationAttendancePolicy for the given organization,
    or transparently creates a default one if none exists.
    """
    from apps.organizations.models import OrganizationAttendancePolicy
    policy, _ = OrganizationAttendancePolicy.objects.get_or_create(
        organization=organization,
        defaults={
            'default_session_duration_minutes': 60,
            'late_after_minutes': 15,
            'allowed_radius_meters': 200.0,
            'max_location_accuracy_meters': 200.0,
            'location_max_age_seconds': 300,
            'accuracy_tolerance_meters': 75.0,
            'challenge_ttl_seconds': 1000,
        }
    )
    return policy


def validate_opener_location(latitude, longitude, location_accuracy_meters=None, location_captured_at=None, max_accuracy_allowed=None, max_age_allowed=None):
    """
    Validates mobile opener location payload using organization policy thresholds.
    Returns (lat_float, lon_float, accuracy_float, captured_at_dt).
    Raises ValueError(message, code) if invalid.
    """
    max_acc = max_accuracy_allowed or ATTENDANCE_MAX_LOCATION_ACCURACY_METERS
    max_age = max_age_allowed or ATTENDANCE_LOCATION_MAX_AGE_SECONDS

    if latitude is None or longitude is None:
        raise ValueError('Session location coordinates are required', 'SESSION_LOCATION_REQUIRED')

    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        raise ValueError('Invalid session location coordinates', 'SESSION_LOCATION_INVALID')

    from apps.locations.utils import validate_coordinates
    if not validate_coordinates(lat, lon):
        raise ValueError('Session location coordinates out of geographic bounds', 'SESSION_LOCATION_INVALID')

    # Accuracy validation
    if location_accuracy_meters is None:
        raise ValueError('Session location accuracy is required', 'SESSION_LOCATION_ACCURACY_INVALID')

    try:
        accuracy = float(location_accuracy_meters)
    except (TypeError, ValueError):
        raise ValueError('Invalid session location accuracy', 'SESSION_LOCATION_ACCURACY_INVALID')

    if accuracy <= 0 or accuracy > max_acc:
        raise ValueError(
            f'Location accuracy too poor ({accuracy}m > max {max_acc}m)',
            'SESSION_LOCATION_ACCURACY_INVALID'
        )

    # Timestamp validation
    if location_captured_at is None:
        raise ValueError('Location captured timestamp is required', 'SESSION_LOCATION_STALE')

    if isinstance(location_captured_at, str):
        try:
            from django.utils.dateparse import parse_datetime
            captured_dt = parse_datetime(location_captured_at)
            if captured_dt is None:
                raise ValueError()
            if timezone.is_naive(captured_dt):
                captured_dt = timezone.make_aware(captured_dt, timezone.get_current_timezone())
        except Exception:
            raise ValueError('Invalid location timestamp format', 'SESSION_LOCATION_STALE')
    elif isinstance(location_captured_at, (int, float)):
        try:
            from datetime import datetime as dt_cls, timezone as dt_timezone
            captured_dt = dt_cls.fromtimestamp(location_captured_at, tz=dt_timezone.utc)
        except Exception:
            raise ValueError('Invalid location timestamp format', 'SESSION_LOCATION_STALE')
    elif isinstance(location_captured_at, datetime):
        captured_dt = location_captured_at
        if timezone.is_naive(captured_dt):
            captured_dt = timezone.make_aware(captured_dt, timezone.get_current_timezone())
    else:
        raise ValueError('Invalid location timestamp', 'SESSION_LOCATION_STALE')

    now = timezone.now()
    age_seconds = (now - captured_dt).total_seconds()

    if age_seconds > max_age:
        raise ValueError(f'Location timestamp is stale ({int(age_seconds)}s old)', 'SESSION_LOCATION_STALE')

    if age_seconds < -ATTENDANCE_LOCATION_MAX_FUTURE_SKEW_SECONDS:
        raise ValueError('Location timestamp is in the future beyond permitted clock skew', 'SESSION_LOCATION_STALE')

    return lat, lon, accuracy, captured_dt


@transaction.atomic
def open_occurrence_session(user, occurrence_id, latitude=None, longitude=None, location_accuracy_meters=None, location_captured_at=None, duration_minutes=60, late_after_minutes=15, radius_meters=ATTENDANCE_DEFAULT_RADIUS_METERS, **kwargs):
    """
    Opens an attendance session for a valid SessionOccurrence.
    Enforces role authorization (DOCTOR or TEACHING_ASSISTANT only) & 1-to-1 occurrence constraint.
    """
    if user.role not in [Role.DOCTOR, Role.TEACHING_ASSISTANT]:
        raise ValueError('Only Doctors and Teaching Assistants can open attendance sessions', 'UNAUTHORIZED_SESSION_OPENER')

    try:
        occ = SessionOccurrence.objects.select_related(
            'course_offering__doctor__user', 'group__teaching_assistant__user', 'course_offering__course'
        ).get(pk=occurrence_id)
    except SessionOccurrence.DoesNotExist:
        raise ValueError('Session occurrence not found', 'SESSION_NOT_SCHEDULED')

    org = user.organization
    if occ.course_offering.course.organization_id != org.id:
        raise ValueError('Not authorized for this organization', 'COURSE_NOT_IN_SCOPE')

    # Check role & academic scope
    if user.role == Role.DOCTOR:
        if occ.session_type != 'LECTURE':
            raise ValueError('Doctors can only open LECTURE occurrences', 'INVALID_SESSION_TYPE')
        if not occ.course_offering.doctor or occ.course_offering.doctor.user_id != user.id:
            raise ValueError('You do not own this course offering', 'COURSE_NOT_IN_SCOPE')
    elif user.role == Role.TEACHING_ASSISTANT:
        if occ.session_type not in ['LAB', 'TUTORIAL']:
            raise ValueError('Teaching Assistants can only open LAB or TUTORIAL occurrences', 'INVALID_SESSION_TYPE')
        if not occ.group or not occ.group.teaching_assistant or occ.group.teaching_assistant.user_id != user.id:
            raise ValueError('You are not assigned to this group', 'GROUP_NOT_IN_SCOPE')

    # Occurrence status / 1-to-1 check
    if hasattr(occ, 'attendance_session'):
        att_session = occ.attendance_session
        if att_session.status == SessionStatus.ACTIVE:
            raise ValueError('Session is already open', 'OCCURRENCE_ALREADY_ACTIVE')
        else:
            raise ValueError('Session has already been opened and closed', 'SESSION_ALREADY_CLOSED')

    if occ.status != SessionOccurrenceStatus.SCHEDULED:
        if occ.status == SessionOccurrenceStatus.ACTIVE:
            raise ValueError('Occurrence is already active', 'OCCURRENCE_ALREADY_ACTIVE')
        else:
            raise ValueError('Occurrence is already completed or cancelled', 'SESSION_ALREADY_CLOSED')

    policy = get_organization_policy(org)

    # Validate location against dynamic policy
    lat, lon, accuracy, captured_at = validate_opener_location(
        latitude=latitude,
        longitude=longitude,
        location_accuracy_meters=location_accuracy_meters,
        location_captured_at=location_captured_at,
        max_accuracy_allowed=policy.max_location_accuracy_meters,
        max_age_allowed=policy.location_max_age_seconds,
    )

    # Resolve timing & geofencing from dynamic policy unless staff override is permitted
    effective_duration = duration_minutes if (policy.allow_staff_custom_duration and duration_minutes is not None) else (duration_minutes or policy.default_session_duration_minutes)
    effective_late_after = late_after_minutes if late_after_minutes is not None else policy.late_after_minutes
    effective_radius = radius_meters if (policy.allow_staff_custom_radius and radius_meters is not None) else policy.allowed_radius_meters
    effective_max_accuracy = policy.max_location_accuracy_meters

    now = timezone.now()
    expires_at = now + timedelta(minutes=effective_duration)

    session = AttendanceSession.objects.create(
        occurrence=occ,
        organization=org,
        opened_by=user,
        latitude=lat,
        longitude=lon,
        location_accuracy_meters=accuracy,
        location_captured_at=captured_at,
        radius_meters=effective_radius,
        max_location_accuracy_meters=effective_max_accuracy,
        late_after_minutes=effective_late_after,
        status=SessionStatus.ACTIVE,
        starts_at=now,
        expires_at=expires_at,
    )

    occ.status = SessionOccurrenceStatus.ACTIVE
    occ.save(update_fields=['status'])

    audit(
        action=AuditAction.SESSION_OPENED,
        actor=user,
        organization=org,
        target_type='AttendanceSession',
        target_id=session.id,
        metadata={
            'occurrence_id': occ.id,
            'session_type': occ.session_type,
            'occurrence_type': occ.occurrence_type,
            'radius_meters': effective_radius,
            'duration_minutes': effective_duration,
            'late_after_minutes': effective_late_after,
        },
    )

    schedule_session_auto_close(session.id, duration_seconds=int(effective_duration * 60))

    return session


@transaction.atomic
def create_and_open_adhoc_session(user, course_offering_id, group_id=None, session_type='LECTURE', latitude=None, longitude=None, location_accuracy_meters=None, location_captured_at=None, duration_minutes=60, late_after_minutes=15, radius_meters=ATTENDANCE_DEFAULT_RADIUS_METERS, **kwargs):
    """
    Creates an ad-hoc SessionOccurrence and immediately opens its AttendanceSession in one atomic operation.
    """
    if user.role not in [Role.DOCTOR, Role.TEACHING_ASSISTANT]:
        raise ValueError('Only Doctors and Teaching Assistants can open attendance sessions', 'UNAUTHORIZED_SESSION_OPENER')

    from apps.courses.models import CourseOffering
    try:
        offering = CourseOffering.objects.select_related('course', 'doctor__user').get(
            pk=course_offering_id,
            course__organization=user.organization,
            status='ACTIVE',
        )
    except CourseOffering.DoesNotExist:
        raise ValueError('Course offering not found or not active', 'COURSE_NOT_IN_SCOPE')

    if user.role == Role.DOCTOR:
        if not offering.doctor or offering.doctor.user_id != user.id:
            raise ValueError('You do not own this course offering', 'COURSE_NOT_IN_SCOPE')
    elif user.role == Role.TEACHING_ASSISTANT:
        if session_type == 'LECTURE':
            raise ValueError('Teaching Assistants cannot create LECTURE sessions', 'INVALID_SESSION_TYPE')

    group = None
    if group_id:
        from apps.groups.models import Group
        try:
            group = Group.objects.select_related('teaching_assistant__user').get(
                pk=group_id,
                course_offering=offering,
                status='ACTIVE',
            )
        except Group.DoesNotExist:
            raise ValueError('Group not found in this course offering', 'GROUP_NOT_IN_SCOPE')

        if user.role == Role.TEACHING_ASSISTANT:
            if not group.teaching_assistant or group.teaching_assistant.user_id != user.id:
                raise ValueError('You are not assigned to this group', 'GROUP_NOT_IN_SCOPE')
    else:
        if user.role == Role.TEACHING_ASSISTANT:
            raise ValueError('Teaching Assistants must select an assigned group', 'GROUP_NOT_IN_SCOPE')

    if session_type not in ['LECTURE', 'LAB', 'TUTORIAL']:
        raise ValueError('Invalid session type', 'INVALID_SESSION_TYPE')

    org = user.organization
    policy = get_organization_policy(org)
    effective_duration = duration_minutes if (policy.allow_staff_custom_duration and duration_minutes is not None) else (duration_minutes or policy.default_session_duration_minutes)

    org_now, today_date, _ = get_org_now_and_today(org)

    starts_dt = org_now
    ends_dt = starts_dt + timedelta(minutes=effective_duration)

    occ = SessionOccurrence.objects.create(
        occurrence_type=OccurrenceType.AD_HOC,
        schedule=None,
        course_offering=offering,
        group=group,
        scheduled_date=today_date,
        starts_at=starts_dt,
        ends_at=ends_dt,
        session_type=session_type,
        status=SessionOccurrenceStatus.SCHEDULED,
    )

    audit(
        action=AuditAction.SESSION_CREATED,
        actor=user,
        organization=org,
        target_type='SessionOccurrence',
        target_id=occ.id,
        metadata={
            'course_offering_id': offering.id,
            'group_id': group.id if group else None,
            'session_type': session_type,
            'occurrence_type': OccurrenceType.AD_HOC,
        },
    )

    session = open_occurrence_session(
        user=user,
        occurrence_id=occ.id,
        latitude=latitude,
        longitude=longitude,
        location_accuracy_meters=location_accuracy_meters,
        location_captured_at=location_captured_at,
        duration_minutes=effective_duration,
        late_after_minutes=late_after_minutes,
        radius_meters=radius_meters,
    )

    return session


@transaction.atomic
def close_attendance_session(user, session_id):
    """
    Closes an active attendance session permanently. NO REOPEN.
    """
    try:
        session = AttendanceSession.objects.select_related(
            'occurrence__course_offering__doctor__user',
            'occurrence__group__teaching_assistant__user',
        ).get(pk=session_id, organization=user.organization)
    except AttendanceSession.DoesNotExist:
        raise ValueError('Attendance session not found', 'SESSION_NOT_FOUND')

    if session.status != SessionStatus.ACTIVE:
        raise ValueError(f'Session is already {session.status.lower()}', 'SESSION_ALREADY_CLOSED')

    # Scope authorization
    occ = session.occurrence
    if user.role == Role.DOCTOR:
        if not occ.course_offering.doctor or occ.course_offering.doctor.user_id != user.id:
            raise ValueError('Not authorized to close this session', 'COURSE_NOT_OWNED')
    elif user.role == Role.TEACHING_ASSISTANT:
        if not occ.group or not occ.group.teaching_assistant or occ.group.teaching_assistant.user_id != user.id:
            raise ValueError('Not authorized to close this session', 'GROUP_NOT_ASSIGNED')

    now = timezone.now()
    session.status = SessionStatus.CLOSED
    session.closed_at = now
    session.save(update_fields=['status', 'closed_at'])

    occ.status = SessionOccurrenceStatus.COMPLETED
    occ.save(update_fields=['status'])

    cancel_session_auto_close(session.id)

    return session


def update_attendance_session(session, **kwargs):
    """
    Updates attendance session fields. Protects opening/location metadata from modification on ACTIVE sessions.
    """
    IMMUTABLE_FIELDS = {'opened_by', 'starts_at', 'latitude', 'longitude', 'location_accuracy_meters', 'location_captured_at', 'radius_meters'}
    if session.status == SessionStatus.ACTIVE:
        modified_immutable = IMMUTABLE_FIELDS.intersection(kwargs.keys())
        if modified_immutable:
            raise ValueError(
                f"Cannot modify immutable opening/location fields on an active session: {', '.join(modified_immutable)}",
                'SESSION_LOCATION_IMMUTABLE'
            )
    for k, v in kwargs.items():
        setattr(session, k, v)
    session.save(update_fields=list(kwargs.keys()))
    return session


def auto_close_expired_sessions(organization=None, session_id=None):
    """
    Event-driven lazy evaluator:
    Finds active attendance sessions where timezone.now() >= expires_at,
    atomically transitions them to CLOSED, sets occurrence status to COMPLETED,
    audits the auto-closure, and broadcasts session.state to WebSockets.
    """
    now = timezone.now()
    qs = AttendanceSession.objects.filter(
        status=SessionStatus.ACTIVE,
        expires_at__lte=now,
    ).select_related('occurrence')

    if organization:
        qs = qs.filter(organization=organization)
    if session_id:
        qs = qs.filter(pk=session_id)

    closed_sessions = []
    for sess in qs:
        try:
            with transaction.atomic():
                sess.status = SessionStatus.CLOSED
                sess.closed_at = now
                sess.save(update_fields=['status', 'closed_at'])

                if sess.occurrence:
                    sess.occurrence.status = SessionOccurrenceStatus.COMPLETED
                    sess.occurrence.save(update_fields=['status'])

                audit(
                    action=AuditAction.SESSION_CLOSED,
                    actor=sess.opened_by,
                    organization=sess.organization,
                    target_type='AttendanceSession',
                    target_id=sess.id,
                    metadata={
                        'occurrence_id': sess.occurrence_id,
                        'reason': 'auto_expired_1hr',
                        'expires_at': sess.expires_at.isoformat() if sess.expires_at else None,
                    },
                )
                closed_sessions.append(sess.id)
        except Exception:
            continue

    if closed_sessions:
        from .signals import broadcast_session_state
        for sid in closed_sessions:
            broadcast_session_state(sid, SessionStatus.CLOSED)

    return closed_sessions


def get_redis_client():
    """Returns a connected Redis client using the configured channel layer host."""
    import redis
    from django.conf import settings
    try:
        hosts = settings.CHANNEL_LAYERS['default']['CONFIG']['hosts']
        redis_url = hosts[0] if hosts else 'redis://localhost:6379/0'
        return redis.Redis.from_url(redis_url)
    except Exception:
        return None


def schedule_session_auto_close(session_id: int, duration_seconds: int = 3600):
    """
    Schedules an auto-close key in Redis with a TTL of duration_seconds (default 1 hour).
    When this key expires in Redis, the broker publishes an event that triggers instant closure.
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        r = get_redis_client()
        if r:
            key = f"session:expiry:{session_id}"
            r.set(key, str(session_id), ex=duration_seconds)
    except Exception as exc:
        logger.warning('Failed to schedule Redis auto-close for session %s: %s', session_id, exc)


def cancel_session_auto_close(session_id: int):
    """
    Cancels the scheduled Redis auto-close key when staff manually closes a session early.
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        r = get_redis_client()
        if r:
            key = f"session:expiry:{session_id}"
            r.delete(key)
    except Exception as exc:
        logger.warning('Failed to cancel Redis auto-close for session %s: %s', session_id, exc)


