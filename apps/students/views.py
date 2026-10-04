"""Students views."""

from rest_framework import generics, filters, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsOrganizationAdmin, IsStudent, IsTeacherOrAdmin
from apps.audit.service import audit
from apps.audit.models import AuditAction

from .models import Student, StudentEnrollment
from .serializers import (
    StudentSerializer, StudentCreateSerializer, CSVImportSerializer,
    StudentEnrollmentSerializer, BulkStudentEnrollmentSerializer,
)


class FlexiblePageNumberPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 1000


def _get_student_response(student):
    """Serialize a student for API response using the read serializer."""
    return StudentSerializer(student).data


class StudentListCreateView(generics.ListCreateAPIView):
    pagination_class = FlexiblePageNumberPagination
    filter_backends = [filters.SearchFilter]
    search_fields = ['student_id', 'user__first_name', 'user__last_name', 'user__email']

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsTeacherOrAdmin()]
        return [IsOrganizationAdmin()]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return StudentCreateSerializer
        return StudentSerializer

    def get_queryset(self):
        qs = Student.objects.filter(
            organization=self.request.user.organization
        ).select_related('user').prefetch_related('enrollments__group').order_by('student_id')

        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        group_id = self.request.query_params.get('group')
        if group_id:
            qs = qs.filter(enrollments__group_id=group_id)

        course_offering_id = self.request.query_params.get('course_offering')
        if course_offering_id:
            qs = qs.filter(enrollments__course_offering_id=course_offering_id)

        return qs.distinct()

    def create(self, request, *args, **kwargs):
        serializer = StudentCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        student = serializer.save()
        audit(
            action=AuditAction.STUDENT_CREATED,
            actor=request.user,
            organization=request.user.organization,
            target_type='Student',
            target_id=student.id,
            metadata={'student_id': student.student_id, 'email': student.user.email},
        )
        return Response(_get_student_response(student), status=status.HTTP_201_CREATED)


class StudentDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsOrganizationAdmin]
    serializer_class = StudentSerializer
    http_method_names = ['get', 'patch', 'delete']

    def get_queryset(self):
        return Student.objects.filter(
            organization=self.request.user.organization
        ).select_related('user').prefetch_related('enrollments__group')

    def perform_update(self, serializer):
        student = serializer.save()
        audit(
            action=AuditAction.STUDENT_UPDATED,
            actor=self.request.user,
            organization=self.request.user.organization,
            target_type='Student',
            target_id=student.id,
        )

    def perform_destroy(self, instance):
        """Soft-delete: archive the student."""
        instance.status = 'ARCHIVED'
        instance.user.is_active = False
        instance.user.save()
        instance.save()
        audit(
            action=AuditAction.STUDENT_DISABLED,
            actor=self.request.user,
            organization=self.request.user.organization,
            target_type='Student',
            target_id=instance.id,
        )


class CSVImportValidateView(APIView):
    """Step 1: upload CSV, get validation preview (does not import)."""
    permission_classes = [IsOrganizationAdmin]

    def post(self, request):
        serializer = CSVImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        valid_rows, invalid_rows, duplicates = serializer.parse_and_validate(
            organization=request.user.organization
        )

        # Strip internal _group_obj (not JSON serializable) from response
        serializable_valid = [
            {k: v for k, v in row.items() if k != '_group_obj'}
            for row in valid_rows
        ]

        return Response({
            'valid_count': len(valid_rows),
            'invalid_count': len(invalid_rows),
            'duplicate_count': len(duplicates),
            'valid_rows': serializable_valid,
            'invalid_rows': invalid_rows,
            'duplicates': duplicates,
        })


class CSVImportExecuteView(APIView):
    """Step 2: execute import after preview confirmation."""
    permission_classes = [IsOrganizationAdmin]

    def post(self, request):
        serializer = CSVImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        valid_rows, invalid_rows, duplicates = serializer.parse_and_validate(
            organization=request.user.organization
        )

        if not valid_rows:
            return Response(
                {'detail': 'No valid rows to import', 'invalid_rows': invalid_rows},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            created = serializer.import_rows(valid_rows, organization=request.user.organization)
        except Exception as exc:
            return Response(
                {'detail': f'Import failed: {exc}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        audit(
            action=AuditAction.STUDENT_IMPORTED,
            actor=request.user,
            organization=request.user.organization,
            metadata={
                'imported': len(created),
                'skipped_duplicates': len(duplicates),
                'invalid': len(invalid_rows),
            },
        )

        return Response({
            'imported': len(created),
            'skipped_duplicates': len(duplicates),
            'invalid_rows': invalid_rows,
        }, status=status.HTTP_201_CREATED)


class MyProfileView(generics.RetrieveAPIView):
    """Student can view their own profile."""
    permission_classes = [IsStudent]
    serializer_class = StudentSerializer

    def get_object(self):
        return self.request.user.student_profile


class UpdatePersonalEmailView(APIView):
    """Student can update their personal email (Gmail) for fallback communications."""
    permission_classes = [IsStudent]

    def post(self, request):
        email = request.data.get('personal_email')
        if not email or '@' not in email:
            return Response({'detail': 'A valid personal_email is required.'}, status=status.HTTP_400_BAD_REQUEST)
        
        student = request.user.student_profile
        student.personal_email = email
        student.save()
        
        audit(
            action=AuditAction.STUDENT_UPDATED,
            actor=request.user,
            organization=request.user.organization,
            target_type='Student',
            target_id=student.id,
            metadata={'updated_field': 'personal_email'}
        )
        return Response({'detail': 'Personal email updated successfully', 'personal_email': email})


class StudentEnrollmentListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsTeacherOrAdmin]
    serializer_class = StudentEnrollmentSerializer
    pagination_class = FlexiblePageNumberPagination

    def get_queryset(self):
        user = self.request.user
        return StudentEnrollment.objects.filter(
            student__organization=user.organization
        ).select_related('student__user', 'course_offering__course', 'group')


class BulkStudentEnrollmentView(APIView):
    """
    Bulk enroll a student into multiple course offerings in a single request.
    `POST /api/v1/students/<id>/bulk-enroll/`
    """
    permission_classes = [IsOrganizationAdmin]

    def post(self, request, pk):
        from django.db import transaction
        from apps.courses.models import CourseOffering
        from apps.groups.models import Group

        try:
            student = Student.objects.get(pk=pk, organization=request.user.organization)
        except Student.DoesNotExist:
            return Response({'detail': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = BulkStudentEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        created_enrollments = []
        errors = []

        with transaction.atomic():
            for idx, item in enumerate(serializer.validated_data['enrollments']):
                offering_id = item['course_offering_id']
                group_id = item.get('group_id')

                try:
                    offering = CourseOffering.objects.get(pk=offering_id, course__organization=request.user.organization)
                except CourseOffering.DoesNotExist:
                    errors.append(f"Item #{idx}: Course offering {offering_id} not found in organization.")
                    continue

                group_obj = None
                if group_id:
                    try:
                        group_obj = Group.objects.get(pk=group_id, course_offering=offering)
                    except Group.DoesNotExist:
                        errors.append(f"Item #{idx}: Group {group_id} does not belong to course offering {offering_id}.")
                        continue

                enrollment, created = StudentEnrollment.objects.update_or_create(
                    student=student,
                    course_offering=offering,
                    defaults={'group': group_obj}
                )
                created_enrollments.append(enrollment)

            if errors:
                transaction.set_rollback(True)
                return Response({'detail': 'Bulk enrollment validation failed', 'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            StudentEnrollmentSerializer(created_enrollments, many=True).data,
            status=status.HTTP_201_CREATED,
        )
