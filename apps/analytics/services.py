"""
Analytics domain service — multi-dimensional attendance & academic reporting engine over Django + PostgreSQL.
"""

from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncWeek
from apps.attendance.models import AttendanceSession, AttendanceRecord, SessionOccurrence
from apps.students.models import StudentEnrollment, Student
from apps.courses.models import AcademicYear, Semester, CourseOffering
from apps.groups.models import Group


class AnalyticsService:
    def __init__(self, organization=None):
        self.organization = organization

    def _get_scoped_sessions(
        self,
        academic_year_id=None,
        semester_id=None,
        course_offering_id=None,
        group_id=None,
        session_type=None,
        start_date=None,
        end_date=None,
        doctor_id=None,
        ta_id=None,
    ):
        sessions = AttendanceSession.objects.all()

        if self.organization:
            sessions = sessions.filter(organization=self.organization)

        if academic_year_id:
            sessions = sessions.filter(occurrence__course_offering__academic_year_id=academic_year_id)
        if semester_id:
            sessions = sessions.filter(occurrence__course_offering__semester_id=semester_id)
        if course_offering_id:
            sessions = sessions.filter(occurrence__course_offering_id=course_offering_id)
        if group_id:
            sessions = sessions.filter(occurrence__group_id=group_id)
        if session_type:
            sessions = sessions.filter(occurrence__session_type=session_type)
        if start_date:
            sessions = sessions.filter(occurrence__scheduled_date__gte=start_date)
        if end_date:
            sessions = sessions.filter(occurrence__scheduled_date__lte=end_date)
        if doctor_id:
            sessions = sessions.filter(occurrence__course_offering__doctor_id=doctor_id)
        if ta_id:
            sessions = sessions.filter(occurrence__group__teaching_assistant_id=ta_id)

        return sessions

    def calculate_metrics(
        self,
        academic_year_id=None,
        semester_id=None,
        course_offering_id=None,
        group_id=None,
        session_type=None,
        start_date=None,
        end_date=None,
        doctor_id=None,
        ta_id=None,
    ):
        """
        Reusable metric calculation engine.
        Returns present, late, excused, cheating, derived_absent counts, percentages, and trends.
        """
        sessions = self._get_scoped_sessions(
            academic_year_id=academic_year_id,
            semester_id=semester_id,
            course_offering_id=course_offering_id,
            group_id=group_id,
            session_type=session_type,
            start_date=start_date,
            end_date=end_date,
            doctor_id=doctor_id,
            ta_id=ta_id,
        )

        session_ids = list(sessions.values_list('id', flat=True))
        records = AttendanceRecord.objects.filter(session_id__in=session_ids)

        counts = records.aggregate(
            present=Count('id', filter=Q(status='PRESENT')),
            late=Count('id', filter=Q(status='LATE')),
            excused=Count('id', filter=Q(status='EXCUSED')),
            cheating=Count('id', filter=Q(status='CHEATING')),
            total_records=Count('id'),
        )

        present_cnt = counts['present'] or 0
        late_cnt = counts['late'] or 0
        excused_cnt = counts['excused'] or 0
        cheating_cnt = counts['cheating'] or 0
        total_records = counts['total_records'] or 0

        # Derived absence calculation:
        # For all completed/closed/expired sessions in scope, calculate expected enrolled students minus actual records
        derived_absent_cnt = 0
        completed_sessions = sessions.filter(status__in=['CLOSED', 'EXPIRED']).select_related('occurrence')
        for s in completed_sessions:
            occ = s.occurrence
            enrollment_qs = StudentEnrollment.objects.filter(course_offering_id=occ.course_offering_id)
            if occ.group_id:
                enrollment_qs = enrollment_qs.filter(group_id=occ.group_id)
            expected_students = enrollment_qs.count()
            actual_records = AttendanceRecord.objects.filter(session=s).count()
            derived_absent_cnt += max(0, expected_students - actual_records)

        grand_total = total_records + derived_absent_cnt
        att_pct = round((present_cnt + late_cnt) / grand_total * 100.0, 1) if grand_total > 0 else 0.0
        late_pct = round(late_cnt / grand_total * 100.0, 1) if grand_total > 0 else 0.0

        # Session type breakdown
        session_type_breakdown = {}
        for stype in ['LECTURE', 'LAB', 'TUTORIAL']:
            stype_sessions = [s for s in completed_sessions if s.occurrence.session_type == stype]
            stype_session_ids = [s.id for s in stype_sessions]
            stype_records = records.filter(session_id__in=stype_session_ids)
            stype_counts = stype_records.aggregate(
                p=Count('id', filter=Q(status='PRESENT')),
                l=Count('id', filter=Q(status='LATE')),
                e=Count('id', filter=Q(status='EXCUSED')),
                c=Count('id', filter=Q(status='CHEATING')),
            )
            stype_p = stype_counts['p'] or 0
            stype_l = stype_counts['l'] or 0
            stype_tot = (stype_counts['p'] or 0) + (stype_counts['l'] or 0) + (stype_counts['e'] or 0) + (stype_counts['c'] or 0)
            stype_att_pct = round((stype_p + stype_l) / stype_tot * 100.0, 1) if stype_tot > 0 else 0.0

            session_type_breakdown[stype] = {
                'sessions_count': len(stype_sessions),
                'present': stype_p,
                'late': stype_l,
                'excused': stype_counts['e'] or 0,
                'cheating': stype_counts['c'] or 0,
                'attendance_percentage': stype_att_pct,
            }

        # Weekly trend calculation
        weekly_trends = []
        weekly_sessions = sessions.annotate(week=TruncWeek('starts_at')).values('week').annotate(
            count=Count('id')
        ).order_by('week')

        for item in weekly_sessions:
            w_start = item['week']
            if not w_start:
                continue
            w_end = w_start + timedelta(weeks=1)
            w_sessions = sessions.filter(starts_at__gte=w_start, starts_at__lt=w_end)
            w_ids = list(w_sessions.values_list('id', flat=True))
            w_recs = records.filter(session_id__in=w_ids)
            w_p = w_recs.filter(status='PRESENT').count()
            w_l = w_recs.filter(status='LATE').count()
            w_tot = w_recs.count()
            w_pct = round((w_p + w_l) / w_tot * 100.0, 1) if w_tot > 0 else 0.0
            weekly_trends.append({
                'week_start': w_start.strftime('%Y-%m-%d') if hasattr(w_start, 'strftime') else str(w_start),
                'sessions_count': item['count'],
                'present': w_p,
                'late': w_l,
                'attendance_percentage': w_pct,
            })

        return {
            'total_sessions': len(session_ids),
            'present_count': present_cnt,
            'late_count': late_cnt,
            'excused_count': excused_cnt,
            'cheating_count': cheating_cnt,
            'derived_absent_count': derived_absent_cnt,
            'total_attendance_records': total_records,
            'attendance_percentage': att_pct,
            'late_percentage': late_pct,
            'session_type_breakdown': session_type_breakdown,
            'weekly_trends': weekly_trends,
        }

    def get_filter_options(self, user=None):
        """Return available dropdown options for filtering analytics."""
        org = self.organization or (user.organization if user else None)
        years = AcademicYear.objects.filter(organization=org).values('id', 'name') if org else AcademicYear.objects.all().values('id', 'name')
        semesters = Semester.objects.filter(organization=org).values('id', 'name') if org else Semester.objects.all().values('id', 'name')

        offerings_qs = CourseOffering.objects.filter(course__organization=org, status='ACTIVE').select_related('course') if org else CourseOffering.objects.all().select_related('course')
        if user and user.role == 'DOCTOR':
            offerings_qs = offerings_qs.filter(doctor__user=user)
        elif user and user.role == 'TEACHING_ASSISTANT':
            offerings_qs = offerings_qs.filter(groups__teaching_assistant__user=user).distinct()
        offerings = [{'id': o.id, 'name': f"{o.course.code} — {o.course.name}"} for o in offerings_qs]

        groups_qs = Group.objects.filter(course_offering__course__organization=org, status='ACTIVE') if org else Group.objects.all()
        if user and user.role == 'DOCTOR':
            groups_qs = groups_qs.filter(course_offering__doctor__user=user)
        elif user and user.role == 'TEACHING_ASSISTANT':
            groups_qs = groups_qs.filter(teaching_assistant__user=user)
        groups = [{'id': g.id, 'name': g.name} for g in groups_qs]

        return {
            'academic_years': list(years),
            'semesters': list(semesters),
            'course_offerings': offerings,
            'groups': groups,
            'session_types': [
                {'id': 'LECTURE', 'name': 'Lecture'},
                {'id': 'LAB', 'name': 'Lab'},
                {'id': 'TUTORIAL', 'name': 'Tutorial'},
            ],
        }

    def _scope_sessions_for_user(self, user, sessions=None):
        """Apply the authenticated user's analytics scope to a session queryset."""
        sessions = sessions if sessions is not None else AttendanceSession.objects.all()
        if user.role == 'SUPERADMIN':
            return sessions
        if not user.organization_id:
            return sessions.none()
        sessions = sessions.filter(organization_id=user.organization_id)
        if user.role == 'DOCTOR':
            return sessions.filter(occurrence__course_offering__doctor__user_id=user.id)
        if user.role == 'TEACHING_ASSISTANT':
            return sessions.filter(occurrence__group__teaching_assistant__user_id=user.id)
        if user.role in ('ADMIN', 'SUPERADMIN'):
            return sessions
        return sessions.none()

    def _filtered_sessions_for_user(self, user, filters=None):
        filters = filters or {}
        sessions = self._scope_sessions_for_user(user)
        field_map = {
            'academic_year_id': 'occurrence__course_offering__academic_year_id',
            'semester_id': 'occurrence__course_offering__semester_id',
            'course_offering_id': 'occurrence__course_offering_id',
            'group_id': 'occurrence__group_id',
            'session_type': 'occurrence__session_type',
            'start_date': 'occurrence__scheduled_date__gte',
            'end_date': 'occurrence__scheduled_date__lte',
        }
        for key, field in field_map.items():
            if filters.get(key):
                sessions = sessions.filter(**{field: filters[key]})
        return sessions.select_related(
            'occurrence__course_offering__course',
            'occurrence__course_offering__academic_year',
            'occurrence__course_offering__semester',
            'occurrence__group',
        ).order_by('occurrence__scheduled_date', 'starts_at')

    def _eligible_enrollments(self, user, filters=None, student_id=None):
        filters = filters or {}
        enrollments = StudentEnrollment.objects.filter(
            student__status='ACTIVE',
            course_offering__status='ACTIVE',
        ).select_related('student__user', 'group', 'course_offering__course')
        if user.role != 'SUPERADMIN':
            enrollments = enrollments.filter(student__organization_id=user.organization_id)
        if user.role == 'DOCTOR':
            enrollments = enrollments.filter(course_offering__doctor__user_id=user.id)
        elif user.role == 'TEACHING_ASSISTANT':
            enrollments = enrollments.filter(group__teaching_assistant__user_id=user.id)
        elif user.role not in ('ADMIN', 'SUPERADMIN'):
            return enrollments.none()
        if filters.get('academic_year_id'):
            enrollments = enrollments.filter(course_offering__academic_year_id=filters['academic_year_id'])
        if filters.get('semester_id'):
            enrollments = enrollments.filter(course_offering__semester_id=filters['semester_id'])
        if filters.get('course_offering_id'):
            enrollments = enrollments.filter(course_offering_id=filters['course_offering_id'])
        if filters.get('group_id'):
            enrollments = enrollments.filter(group_id=filters['group_id'])
        if student_id:
            enrollments = enrollments.filter(student_id=student_id)
        return enrollments

    @staticmethod
    def _session_matches_enrollment(session, enrollment):
        return (
            session.occurrence.course_offering_id == enrollment.course_offering_id
            and (session.occurrence.group_id is None or session.occurrence.group_id == enrollment.group_id)
        )

    @staticmethod
    def _attendance_rate(present, late, excused, eligible):
        denominator = eligible - excused
        return round((present + late) / denominator * 100.0, 1) if denominator > 0 else 0.0

    def student_summary_rows(self, user, filters=None):
        """Return one derived attendance summary row per visible student."""
        filters = filters or {}
        sessions = list(self._filtered_sessions_for_user(user, filters).filter(status__in=['CLOSED', 'EXPIRED']))
        enrollments = list(self._eligible_enrollments(user, filters))
        session_ids = [session.id for session in sessions]
        records = AttendanceRecord.objects.filter(session_id__in=session_ids).values(
            'session_id', 'student_id', 'status', 'verified_at'
        )
        record_map = {(record['session_id'], record['student_id']): record for record in records}
        by_student = {}
        for enrollment in enrollments:
            row = by_student.setdefault(enrollment.student_id, {
                'student_pk': enrollment.student_id,
                'student_id': enrollment.student.student_id,
                'student_name': enrollment.student.user.get_full_name(),
                'group': set(),
                'eligible_sessions': 0,
                'present': 0,
                'late': 0,
                'excused': 0,
                'cheating': 0,
                'absent': 0,
            })
            if enrollment.group:
                row['group'].add(enrollment.group.name)
            relevant_sessions = [session for session in sessions if self._session_matches_enrollment(session, enrollment)]
            for session in relevant_sessions:
                row['eligible_sessions'] += 1
                record = record_map.get((session.id, enrollment.student_id))
                if not record:
                    row['absent'] += 1
                else:
                    row[record['status'].lower()] += 1
        rows = []
        for row in by_student.values():
            row['group'] = ', '.join(sorted(row['group'])) or 'All Groups'
            row['attendance_rate'] = self._attendance_rate(
                row['present'], row['late'], row['excused'], row['eligible_sessions']
            )
            rows.append(row)
        search = (filters.get('search') or '').strip().lower()
        if search:
            rows = [row for row in rows if search in row['student_id'].lower() or search in row['student_name'].lower()]
        if filters.get('attendance_status'):
            status_key = filters['attendance_status'].lower()
            rows = [row for row in rows if row.get(status_key, 0) > 0]
        return rows

    def session_attendance_rows(self, user, session_id, filters=None):
        """Return every eligible student for one authorized session, including ABSENT."""
        filters = filters or {}
        sessions = self._scope_sessions_for_user(user).filter(id=session_id).select_related(
            'occurrence__course_offering__course', 'occurrence__group'
        )
        session = sessions.first()
        if not session:
            return None, []
        enrollments = list(self._eligible_enrollments(user, filters).filter(
            course_offering_id=session.occurrence.course_offering_id
        ))
        if session.occurrence.group_id:
            enrollments = [enrollment for enrollment in enrollments if enrollment.group_id == session.occurrence.group_id]
        records = {
            record.student_id: record for record in AttendanceRecord.objects.filter(
                session=session, student_id__in=[enrollment.student_id for enrollment in enrollments]
            ).select_related('student__user')
        }
        rows = []
        for enrollment in enrollments:
            record = records.get(enrollment.student_id)
            rows.append({
                'student_id': enrollment.student.student_id,
                'student_name': enrollment.student.user.get_full_name(),
                'group': enrollment.group.name if enrollment.group else 'All Groups',
                'status': record.status if record else 'ABSENT',
                'attendance_time': record.verified_at.isoformat() if record else None,
                'distance_from_session_location': record.distance_from_location_meters if record else None,
                'location_accuracy': record.location_accuracy_meters if record else None,
            })
        if filters.get('attendance_status'):
            rows = [row for row in rows if row['status'] == filters['attendance_status']]
        return session, rows

    def student_history_rows(self, user, student_id, filters=None):
        """Return the authorized student's session history with derived absences."""
        filters = dict(filters or {})
        enrollments = list(self._eligible_enrollments(user, filters, student_id=student_id))
        if not enrollments:
            return []
        sessions = list(self._filtered_sessions_for_user(user, filters).filter(status__in=['CLOSED', 'EXPIRED']))
        records = {
            record.session_id: record for record in AttendanceRecord.objects.filter(
                session_id__in=[session.id for session in sessions], student_id=student_id
            )
        }
        rows = []
        for session in sessions:
            if not any(self._session_matches_enrollment(session, enrollment) for enrollment in enrollments):
                continue
            record = records.get(session.id)
            rows.append({
                'date': session.occurrence.scheduled_date.isoformat(),
                'course': session.occurrence.course_offering.course.code,
                'group': session.occurrence.group.name if session.occurrence.group else 'All Groups',
                'session_type': session.occurrence.session_type,
                'session_id': session.id,
                'status': record.status if record else 'ABSENT',
                'attendance_time': record.verified_at.isoformat() if record else None,
                'distance_from_session_location': record.distance_from_location_meters if record else None,
                'location_accuracy': record.location_accuracy_meters if record else None,
            })
        if filters.get('attendance_status'):
            rows = [row for row in rows if row['status'] == filters['attendance_status']]
        return rows

    def session_list_rows(self, user, filters=None):
        """Return visible sessions for browser/API drill-down navigation."""
        return [{
            'session_id': session.id,
            'date': session.occurrence.scheduled_date.isoformat(),
            'course': session.occurrence.course_offering.course.code,
            'course_name': session.occurrence.course_offering.course.name,
            'group': session.occurrence.group.name if session.occurrence.group else 'All Groups',
            'session_type': session.occurrence.session_type,
            'status': session.status,
        } for session in self._filtered_sessions_for_user(user, filters)]

