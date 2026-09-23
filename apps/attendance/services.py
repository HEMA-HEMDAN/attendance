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


def get_doctor_today_work(user):
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

    return result


def get_ta_today_work(user):
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

    return result


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


@transaction.atomic
def open_occurrence_session(user, occurrence_id, latitude=None, longitude=None, radius_meters=50.0, duration_minutes=60, late_after_minutes=15):
    """
    Opens an attendance session for a valid SessionOccurrence.
    Enforces role authorization & One-to-One occurrence session constraint.
    """
    try:
        occ = SessionOccurrence.objects.select_related(
            'course_offering__doctor__user', 'group__teaching_assistant__user', 'course_offering__course'
        ).get(pk=occurrence_id)
    except SessionOccurrence.DoesNotExist:
        raise ValueError('Session occurrence not found', 'SESSION_NOT_SCHEDULED')

    org = user.organization
    if occ.course_offering.course.organization_id != org.id:
        raise ValueError('Not authorized for this organization', 'INVALID_ACADEMIC_SCOPE')

    # Check role & academic scope
    if user.role == Role.DOCTOR:
        if occ.session_type != 'LECTURE':
            raise ValueError('Doctors can only open LECTURE occurrences', 'LECTURE_NOT_ALLOWED')
        if not occ.course_offering.doctor or occ.course_offering.doctor.user_id != user.id:
            raise ValueError('You do not own this course offering', 'COURSE_NOT_OWNED')
    elif user.role == Role.TEACHING_ASSISTANT:
        if occ.session_type not in ['LAB', 'TUTORIAL']:
            raise ValueError('Teaching Assistants can only open LAB or TUTORIAL occurrences', 'LECTURE_NOT_ALLOWED')
        if not occ.group or not occ.group.teaching_assistant or occ.group.teaching_assistant.user_id != user.id:
            raise ValueError('You are not assigned to this group', 'GROUP_NOT_ASSIGNED')
    elif user.role not in [Role.ADMIN, Role.SUPERADMIN]:
        raise ValueError('Not authorized to open attendance sessions', 'INVALID_ACADEMIC_SCOPE')

    # 1-to-1 check
    if hasattr(occ, 'attendance_session'):
        att_session = occ.attendance_session
        if att_session.status == SessionStatus.ACTIVE:
            raise ValueError('Session is already open', 'SESSION_ALREADY_OPEN')
        else:
            raise ValueError('Session has already been opened and closed', 'SESSION_ALREADY_CLOSED')

    now = timezone.now()
    expires_at = now + timedelta(minutes=duration_minutes)

    session = AttendanceSession.objects.create(
        occurrence=occ,
        organization=org,
        opened_by=user,
        latitude=latitude,
        longitude=longitude,
        radius_meters=radius_meters,
        late_after_minutes=late_after_minutes,
        status=SessionStatus.ACTIVE,
        starts_at=now,
        expires_at=expires_at,
    )

    occ.status = SessionOccurrenceStatus.ACTIVE
    occ.save(update_fields=['status'])

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

    return session
