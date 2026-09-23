"""
Analytics views — role-scoped analytics APIs.
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.accounts.models import Role
from apps.accounts.permissions import IsDoctor, IsTeachingAssistant, IsOrganizationAdmin, IsSuperadmin
from apps.staff.models import Doctor, TeachingAssistant
from .services import AnalyticsService


class DoctorAnalyticsView(APIView):
    """Doctor Analytics: owned course offerings, all sections, attendance, trends."""
    permission_classes = [IsDoctor]

    def get(self, request):
        doc = Doctor.objects.filter(user=request.user, organization=request.user.organization).first()
        if not doc:
            return Response({'detail': 'Doctor profile not found'}, status=status.HTTP_404_NOT_FOUND)

        svc = AnalyticsService(organization=request.user.organization)

        year_id = request.query_params.get('academic_year_id')
        sem_id = request.query_params.get('semester_id')
        offering_id = request.query_params.get('course_offering_id')
        group_id = request.query_params.get('group_id')

        metrics = svc.calculate_metrics(
            academic_year_id=year_id,
            semester_id=sem_id,
            course_offering_id=offering_id,
            group_id=group_id,
            doctor_id=doc.id,
        )

        offerings = doc.course_offerings.filter(status='ACTIVE').select_related('course')
        offering_summary = []
        for o in offerings:
            m = svc.calculate_metrics(course_offering_id=o.id, doctor_id=doc.id)
            offering_summary.append({
                'course_offering_id': o.id,
                'course_code': o.course.code,
                'course_name': o.course.name,
                'metrics': m,
            })

        return Response({
            'overall_metrics': metrics,
            'course_offerings': offering_summary,
        })


class TeachingAssistantAnalyticsView(APIView):
    """TA Analytics: assigned groups, related courses, attendance."""
    permission_classes = [IsTeachingAssistant]

    def get(self, request):
        ta = TeachingAssistant.objects.filter(user=request.user, organization=request.user.organization).first()
        if not ta:
            return Response({'detail': 'Teaching Assistant profile not found'}, status=status.HTTP_404_NOT_FOUND)

        svc = AnalyticsService(organization=request.user.organization)

        year_id = request.query_params.get('academic_year_id')
        sem_id = request.query_params.get('semester_id')
        group_id = request.query_params.get('group_id')

        metrics = svc.calculate_metrics(
            academic_year_id=year_id,
            semester_id=sem_id,
            group_id=group_id,
            ta_id=ta.id,
        )

        assigned_groups = ta.assigned_groups.filter(status='ACTIVE').select_related('course_offering__course')
        group_summary = []
        for g in assigned_groups:
            m = svc.calculate_metrics(group_id=g.id, ta_id=ta.id)
            group_summary.append({
                'group_id': g.id,
                'group_name': g.name,
                'course_code': g.course_offering.course.code,
                'metrics': m,
            })

        return Response({
            'overall_metrics': metrics,
            'assigned_groups': group_summary,
        })


class OrganizationAdminAnalyticsView(APIView):
    """Organization Admin Analytics: organization-wide metrics."""
    permission_classes = [IsOrganizationAdmin]

    def get(self, request):
        svc = AnalyticsService(organization=request.user.organization)

        year_id = request.query_params.get('academic_year_id')
        sem_id = request.query_params.get('semester_id')
        offering_id = request.query_params.get('course_offering_id')
        group_id = request.query_params.get('group_id')
        sess_type = request.query_params.get('session_type')

        metrics = svc.calculate_metrics(
            academic_year_id=year_id,
            semester_id=sem_id,
            course_offering_id=offering_id,
            group_id=group_id,
            session_type=sess_type,
        )

        from apps.students.models import Student
        from apps.staff.models import Doctor, TeachingAssistant
        from apps.groups.models import Group

        org = request.user.organization
        counts = {
            'total_students': Student.objects.filter(organization=org, status='ACTIVE').count(),
            'total_doctors': Doctor.objects.filter(organization=org).count(),
            'total_tas': TeachingAssistant.objects.filter(organization=org).count(),
            'total_groups': Group.objects.filter(course_offering__course__organization=org, status='ACTIVE').count(),
        }

        return Response({
            'organization_counts': counts,
            'metrics': metrics,
        })


class SuperadminAnalyticsView(APIView):
    """Superadmin Analytics: platform-wide aggregates."""
    permission_classes = [IsSuperadmin]

    def get(self, request):
        svc = AnalyticsService(organization=None)
        metrics = svc.calculate_metrics()

        from apps.organizations.models import Organization
        org_list = []
        for org in Organization.objects.all():
            org_svc = AnalyticsService(organization=org)
            org_list.append({
                'organization_id': org.id,
                'organization_name': org.name,
                'metrics': org_svc.calculate_metrics(),
            })

        return Response({
            'platform_metrics': metrics,
            'organizations': org_list,
        })
