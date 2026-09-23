"""
Analytics domain service — multi-dimensional attendance & academic reporting engine over Django + PostgreSQL.
"""

from django.db.models import Count, Q
from apps.attendance.models import AttendanceSession, AttendanceRecord, SessionOccurrence
from apps.students.models import StudentEnrollment


class AnalyticsService:
    def __init__(self, organization=None):
        self.organization = organization

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
        # For all completed/closed sessions in scope, calculate expected enrolled students minus actual records
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
        }
