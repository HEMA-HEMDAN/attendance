"""
Shared permissions for Bio Attendance.

All permissions enforce server-side authorization.
Organization isolation is mandatory — no cross-tenant data leaks.
"""

from rest_framework.permissions import BasePermission
from apps.accounts.models import Role


class IsOrganizationAdmin(BasePermission):
    """User must be authenticated and have ADMIN role."""

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role == Role.ADMIN
            and request.user.organization_id is not None
        )


class IsTeacher(BasePermission):
    """User must be authenticated and have TEACHER role."""

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role == Role.TEACHER
            and request.user.organization_id is not None
        )


class IsStudent(BasePermission):
    """User must be authenticated, have STUDENT role, and a student_profile."""

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role == Role.STUDENT
            and request.user.organization_id is not None
            and hasattr(request.user, 'student_profile')
        )


class IsAdminOrTeacher(BasePermission):
    """Admin or Teacher."""

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role in (Role.ADMIN, Role.TEACHER)
            and request.user.organization_id is not None
        )


class IsAdminOrReadOnly(BasePermission):
    """Admin for write operations, any authenticated user for read."""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        return request.user.role == Role.ADMIN


class BelongsToSameOrganization(BasePermission):
    """Object-level: the resource's organization must match the user's organization."""

    def has_object_permission(self, request, view, obj):
        org_id = getattr(obj, 'organization_id', None)
        if org_id is None and hasattr(obj, 'organization'):
            org_id = obj.organization.id
        return org_id == request.user.organization_id
