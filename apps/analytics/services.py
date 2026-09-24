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
        years = AcademicYear.objects.filter(organization=org).values('id', 'name') if org else []
        semesters = Semester.objects.filter(organization=org).values('id', 'name') if org else []

        offerings_qs = CourseOffering.objects.filter(course__organization=org, status='ACTIVE').select_related('course') if org else []
        offerings = [{'id': o.id, 'name': f"{o.course.code} — {o.course.name}"} for o in offerings_qs]

        groups_qs = Group.objects.filter(course_offering__course__organization=org, status='ACTIVE') if org else []
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

