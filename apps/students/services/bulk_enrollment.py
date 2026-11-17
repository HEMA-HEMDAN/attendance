import logging
from django.db import transaction, IntegrityError
from django.core.exceptions import ValidationError
from apps.courses.models import CourseOffering, CourseOfferingStatus
from apps.groups.models import Group
from apps.students.models import StudentEnrollment

logger = logging.getLogger(__name__)


class BulkEnrollmentResult:
    """Encapsulates the outcome of a bulk enrollment operation."""
    def __init__(self, total_students, created_count, already_existing_count, rejected_count=0):
        self.total_students = total_students
        self.created_count = created_count
        self.already_existing_count = already_existing_count
        self.rejected_count = rejected_count

    def __iter__(self):
        # Allows legacy tuple unpacking: total, created, already_existing = result
        return iter((self.total_students, self.created_count, self.already_existing_count))

    def __getitem__(self, item):
        return (self.total_students, self.created_count, self.already_existing_count)[item]

    def __repr__(self):
        return (f"<BulkEnrollmentResult: total={self.total_students}, created={self.created_count}, "
                f"existing={self.already_existing_count}, rejected={self.rejected_count}>")


class BulkEnrollmentActionService:
    @classmethod
    def execute_enrollment(
        cls,
        student_queryset,
        offering_ids=None,
        strategy='LECTURE_ONLY',
        specific_group_id=None,
        organization=None,
        offering_groups=None,
        dry_run=False,
    ):
        """
        Enrolls students into one or more course offerings, with optional per-offering group assignments.
        
        Guarantees:
        - Strict tenant isolation: All students, offerings, and groups must belong to organization.
        - Per-offering group integrity: Every assigned group must belong strictly to its offering.
        - Additive-by-default: Existing enrollments are preserved without overwriting or clearing groups.
        - Genuine dry-run preview: When dry_run=True, computes exact metrics with zero database writes.
        - Set-difference batching: bulk_create executes only on missing pairs.
        - Concurrency & Transaction safety: atomic execution with clean collision handling.
        """
        if not organization and hasattr(student_queryset, 'first') and student_queryset.first():
            organization = student_queryset.first().organization

        # 1. Normalize offering & group selections
        is_legacy_call = offering_groups is None
        if offering_groups is not None:
            if isinstance(offering_groups, (list, tuple)):
                offering_groups_dict = dict(offering_groups)
            else:
                offering_groups_dict = dict(offering_groups)
            target_offering_ids = list(offering_groups_dict.keys())
        else:
            target_offering_ids = list(offering_ids) if offering_ids else []
            offering_groups_dict = {oid: specific_group_id for oid in target_offering_ids}

        # 2. Scope & Validate Students
        total_requested = student_queryset.count() if hasattr(student_queryset, 'count') else len(student_queryset)
        valid_students = list(student_queryset.filter(organization=organization)) if hasattr(student_queryset, 'filter') else [
            s for s in student_queryset if s.organization_id == getattr(organization, 'id', organization)
        ]
        rejected_students = total_requested - len(valid_students)

        if not valid_students:
            return BulkEnrollmentResult(0, 0, 0, rejected_count=rejected_students)

        # 3. Scope & Validate Offerings
        valid_offerings = list(CourseOffering.objects.filter(
            id__in=target_offering_ids,
            course__organization=organization,
            status=CourseOfferingStatus.ACTIVE,
        ).select_related('course', 'academic_year', 'semester'))
        rejected_offerings = len(set(target_offering_ids)) - len(valid_offerings)

        if not valid_offerings:
            return BulkEnrollmentResult(
                total_requested,
                0,
                0,
                rejected_count=rejected_students + rejected_offerings
            )

        # 4. Resolve and Validate Per-Offering Target Groups
        offering_by_id = {off.id: off for off in valid_offerings}
        resolved_groups = {}  # offering_id -> Group instance or None

        if is_legacy_call and specific_group_id:
            if len(valid_offerings) > 1:
                raise ValidationError("A specific group can only be assigned when enrolling into exactly one course offering.")
            single_off = valid_offerings[0]
            group_obj = Group.objects.filter(
                id=specific_group_id,
                course_offering=single_off,
                status='ACTIVE'
            ).first()
            if not group_obj:
                raise ValidationError(f"Group ID {specific_group_id} does not belong to course offering '{single_off}'.")
            resolved_groups[single_off.id] = group_obj
        else:
            for off_id, grp_id in offering_groups_dict.items():
                if off_id not in offering_by_id:
                    continue
                off = offering_by_id[off_id]
                if grp_id:
                    group_obj = Group.objects.filter(
                        id=grp_id,
                        course_offering=off,
                        status='ACTIVE'
                    ).first()
                    if not group_obj:
                        raise ValidationError(
                            f"Group ID {grp_id} does not belong to active course offering '{off.course.code}'."
                        )
                    resolved_groups[off.id] = group_obj
                else:
                    resolved_groups[off.id] = None

        # 5. Fetch Existing Enrollments via Set Difference (Single Query)
        existing_pairs = set(StudentEnrollment.objects.filter(
            student__in=valid_students,
            course_offering__in=valid_offerings
        ).values_list('student_id', 'course_offering_id'))

        to_create = []
        already_existing_count = 0

        for student in valid_students:
            for off in valid_offerings:
                if (student.id, off.id) in existing_pairs:
                    already_existing_count += 1
                    # Invariant: Never clear or modify an existing enrollment's group
                else:
                    to_create.append(StudentEnrollment(
                        student=student,
                        course_offering=off,
                        group=resolved_groups.get(off.id)
                    ))

        # 6. Dry-Run Check (Zero Persistent Writes)
        if dry_run:
            return BulkEnrollmentResult(
                total_students=total_requested,
                created_count=len(to_create),
                already_existing_count=already_existing_count,
                rejected_count=rejected_students + rejected_offerings
            )

        # 7. Atomic Batch Insert
        created_count = 0
        try:
            with transaction.atomic():
                if to_create:
                    created_objs = StudentEnrollment.objects.bulk_create(to_create, batch_size=500)
                    created_count = len(created_objs)
        except IntegrityError as err:
            logger.warning(f"Concurrent enrollment insert collision detected: {err}")
            raise ValidationError("A concurrent enrollment update conflict occurred. Please refresh the page and retry.")

        return BulkEnrollmentResult(
            total_students=total_requested,
            created_count=created_count,
            already_existing_count=already_existing_count,
            rejected_count=rejected_students + rejected_offerings
        )

