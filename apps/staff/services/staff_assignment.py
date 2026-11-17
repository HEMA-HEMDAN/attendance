"""
Staff Assignment Service.

Provides reusable operations for assigning and reassigning academic staff:
- Doctors to Course Offerings (single staff assignee)
- Teaching Assistants to Groups/Sections (single staff assignee)

Guarantees:
- Single-assignee replacement semantics: reassigning an offering or group cleanly
  transfers it to the new staff member, replacing the previous assignment atomically.
- Schedule synchronization: updating an offering's doctor updates lecture schedules;
  updating a group's TA updates lab/tutorial schedules.
- Genuine dry-run preview: computes exact replacement metrics with zero DB writes.
- Strict tenant isolation: prevents assigning cross-tenant staff, courses, or groups.
"""

import logging
from typing import List, Dict, Any, Optional
from django.db import transaction
from django.core.exceptions import ValidationError

from apps.staff.models import Doctor, TeachingAssistant
from apps.courses.models import CourseOffering, CourseOfferingStatus, Schedule
from apps.groups.models import Group, GroupStatus

logger = logging.getLogger(__name__)


class StaffAssignmentResult:
    """Encapsulates the outcome and breakdown of an academic staff assignment operation."""
    def __init__(self, total_items: int, newly_assigned_count: int, reassigned_count: int,
                 unchanged_count: int, rejected_count: int = 0, details: Optional[List[Dict[str, Any]]] = None):
        self.total_items = total_items
        self.newly_assigned_count = newly_assigned_count
        self.reassigned_count = reassigned_count
        self.unchanged_count = unchanged_count
        self.rejected_count = rejected_count
        self.details = details or []

    @property
    def modified_count(self) -> int:
        return self.newly_assigned_count + self.reassigned_count


class StaffAssignmentService:
    """
    Central service for staff course and group assignments with replacement semantics.
    """

    @classmethod
    def assign_doctor_to_offerings(
        cls,
        doctor: Doctor,
        course_offering_ids: List[int],
        organization,
        dry_run: bool = False
    ) -> StaffAssignmentResult:
        """
        Assigns or reassigns a Doctor to one or more Course Offerings.
        
        If an offering is currently led by another Doctor, it is atomically replaced.
        Schedules associated with the offering are synchronized.
        """
        if not doctor or not doctor.pk:
            raise ValidationError("A valid Doctor must be specified.")
        if doctor.organization_id != organization.id:
            raise ValidationError("Doctor does not belong to the target organization.")
        if not course_offering_ids:
            return StaffAssignmentResult(0, 0, 0, 0, 0, [])

        # Fetch offerings and validate tenant boundary
        offerings = list(
            CourseOffering.objects.filter(id__in=course_offering_ids)
            .select_related('course', 'academic_year', 'semester', 'doctor', 'doctor__user')
            .order_by('course__code')
        )

        found_ids = {off.id for off in offerings}
        missing_ids = set(course_offering_ids) - found_ids
        rejected_count = len(missing_ids)

        newly_assigned = 0
        reassigned = 0
        unchanged = 0
        details = []
        valid_offerings = []

        for off in offerings:
            # Enforce organization matching
            if off.course.organization_id != organization.id:
                rejected_count += 1
                continue
            if off.status != CourseOfferingStatus.ACTIVE:
                rejected_count += 1
                continue

            prev_doctor = off.doctor
            if prev_doctor is None:
                action_type = 'NEW'
                newly_assigned += 1
                valid_offerings.append(off)
            elif prev_doctor.id == doctor.id:
                action_type = 'UNCHANGED'
                unchanged += 1
            else:
                action_type = 'REASSIGNED'
                reassigned += 1
                valid_offerings.append(off)

            details.append({
                'offering': off,
                'previous_doctor': prev_doctor,
                'new_doctor': doctor,
                'action_type': action_type,
            })

        if dry_run:
            return StaffAssignmentResult(
                total_items=len(course_offering_ids),
                newly_assigned_count=newly_assigned,
                reassigned_count=reassigned,
                unchanged_count=unchanged,
                rejected_count=rejected_count,
                details=details
            )

        # Atomic execution
        with transaction.atomic():
            for off in valid_offerings:
                off.doctor = doctor
                off.save(update_fields=['doctor', 'updated_at'])

            if valid_offerings:
                # Synchronize lecture schedules for these course offerings
                Schedule.objects.filter(
                    course_offering__in=valid_offerings
                ).update(doctor=doctor)

        logger.info(
            f"Doctor assignment executed: Doctor {doctor.id} assigned to {len(valid_offerings)} offerings "
            f"({newly_assigned} new, {reassigned} reassigned) in org {organization.id}."
        )

        return StaffAssignmentResult(
            total_items=len(course_offering_ids),
            newly_assigned_count=newly_assigned,
            reassigned_count=reassigned,
            unchanged_count=unchanged,
            rejected_count=rejected_count,
            details=details
        )

    @classmethod
    def assign_ta_to_groups(
        cls,
        ta: TeachingAssistant,
        group_ids: List[int],
        organization,
        dry_run: bool = False
    ) -> StaffAssignmentResult:
        """
        Assigns or reassigns a Teaching Assistant to one or more Groups.
        
        If a group is currently instructed by another TA, it is atomically replaced.
        Schedules associated with the group are synchronized via Group.save().
        """
        if not ta or not ta.pk:
            raise ValidationError("A valid Teaching Assistant must be specified.")
        if ta.organization_id != organization.id:
            raise ValidationError("Teaching Assistant does not belong to the target organization.")
        if not group_ids:
            return StaffAssignmentResult(0, 0, 0, 0, 0, [])

        groups = list(
            Group.objects.filter(id__in=group_ids)
            .select_related('course_offering', 'course_offering__course', 'teaching_assistant', 'teaching_assistant__user')
            .order_by('course_offering__course__code', 'name')
        )

        found_ids = {g.id for g in groups}
        missing_ids = set(group_ids) - found_ids
        rejected_count = len(missing_ids)

        newly_assigned = 0
        reassigned = 0
        unchanged = 0
        details = []
        valid_groups = []

        for grp in groups:
            # Enforce organization matching through course_offering
            if grp.course_offering.course.organization_id != organization.id:
                rejected_count += 1
                continue
            if grp.status != GroupStatus.ACTIVE:
                rejected_count += 1
                continue

            prev_ta = grp.teaching_assistant
            if prev_ta is None:
                action_type = 'NEW'
                newly_assigned += 1
                valid_groups.append(grp)
            elif prev_ta.id == ta.id:
                action_type = 'UNCHANGED'
                unchanged += 1
            else:
                action_type = 'REASSIGNED'
                reassigned += 1
                valid_groups.append(grp)

            details.append({
                'group': grp,
                'previous_ta': prev_ta,
                'new_ta': ta,
                'action_type': action_type,
            })

        if dry_run:
            return StaffAssignmentResult(
                total_items=len(group_ids),
                newly_assigned_count=newly_assigned,
                reassigned_count=reassigned,
                unchanged_count=unchanged,
                rejected_count=rejected_count,
                details=details
            )

        # Atomic execution
        with transaction.atomic():
            for grp in valid_groups:
                grp.teaching_assistant = ta
                # Calling save() triggers Group.save() which syncs Schedule.objects.filter(group=grp)
                grp.save()

        logger.info(
            f"TA assignment executed: TA {ta.id} assigned to {len(valid_groups)} groups "
            f"({newly_assigned} new, {reassigned} reassigned) in org {organization.id}."
        )

        return StaffAssignmentResult(
            total_items=len(group_ids),
            newly_assigned_count=newly_assigned,
            reassigned_count=reassigned,
            unchanged_count=unchanged,
            rejected_count=rejected_count,
            details=details
        )
