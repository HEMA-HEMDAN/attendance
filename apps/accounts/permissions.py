"""
Shared permissions for Bio Attendance.

All permissions enforce server-side authorization.
Organization isolation is mandatory — no cross-tenant data leaks.
"""

from rest_framework import permissions

from apps.accounts.models import Role


class IsOrganizationAdmin(permissions.BasePermission):
    """User must be authenticated and have ADMIN role."""

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and request.user.role == Role.ADMIN
            and request.user.organization_id is not None
        )


class IsTeacherOrAdmin(permissions.BasePermission):
    """
    Grants access to Admin and all teaching roles (Doctor, TA).
    """

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated
            and request.user.role in (Role.ADMIN, Role.SUPERADMIN, Role.DOCTOR, Role.TEACHING_ASSISTANT)
        )

# Backward compatible aliases
IsAdminOrTeacher = IsTeacherOrAdmin
IsTeacher = IsTeacherOrAdmin

class IsStudent(permissions.BasePermission):
    """
    Grants access only to Students.
    """

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated
            and request.user.role == Role.STUDENT
        )


class IsOrganizationMember(permissions.BasePermission):
    """
    Object-level permission to ensure the user belongs to the same org
    as the object being accessed.
    Requires the object to have an `organization` or `organization_id` attribute.
    """

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser:
            return True

        if hasattr(obj, 'organization_id'):
            return obj.organization_id == request.user.organization_id
        elif hasattr(obj, 'organization'):
            return obj.organization == request.user.organization
        return False


class IsAdmin(permissions.BasePermission):
    """
    Grants access to Admin and Superadmin.
    """

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated
            and request.user.role in (Role.ADMIN, Role.SUPERADMIN)
            and request.user.organization_id is not None
        )


class IsAdminOrReadOnly(permissions.BasePermission):
    """Admin for write operations, any authenticated user for read."""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        return request.user.role == Role.ADMIN


class BelongsToSameOrganization(permissions.BasePermission):
    """Object-level: the resource's organization must match the user's organization."""

    def has_object_permission(self, request, view, obj):
        org_id = getattr(obj, 'organization_id', None)
        if org_id is None and hasattr(obj, 'organization'):
            org_id = obj.organization.id
        return org_id == request.user.organization_id
