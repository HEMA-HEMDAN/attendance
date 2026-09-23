"""
Permissions for University Attendance Platform.

All permissions enforce server-side role and organization authorization.
Organization isolation is mandatory — no cross-tenant data leaks.
"""

from rest_framework import permissions
from apps.accounts.models import Role


class IsSuperadmin(permissions.BasePermission):
    """Platform Superadmin."""
    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated
            and request.user.role == Role.SUPERADMIN
        )


class IsOrganizationAdmin(permissions.BasePermission):
    """Organization Admin."""
    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated
            and request.user.role in (Role.ADMIN, Role.SUPERADMIN)
            and request.user.organization_id is not None
        )


class IsDoctor(permissions.BasePermission):
    """Doctor role."""
    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated
            and request.user.role == Role.DOCTOR
        )


class IsTeachingAssistant(permissions.BasePermission):
    """Teaching Assistant (Doctor Assistant) role."""
    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated
            and request.user.role == Role.TEACHING_ASSISTANT
        )


class IsDoctorOrAssistant(permissions.BasePermission):
    """Doctor or Teaching Assistant."""
    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated
            and request.user.role in (Role.DOCTOR, Role.TEACHING_ASSISTANT)
        )


class IsStudent(permissions.BasePermission):
    """Student role."""
    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated
            and request.user.role == Role.STUDENT
        )


class IsTeacherOrAdmin(permissions.BasePermission):
    """Grants access to Admin, Superadmin, Doctor, and Teaching Assistant."""
    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated
            and request.user.role in (Role.ADMIN, Role.SUPERADMIN, Role.DOCTOR, Role.TEACHING_ASSISTANT)
        )


IsAdminOrTeacher = IsTeacherOrAdmin
IsAdmin = IsOrganizationAdmin


class IsOrganizationMember(permissions.BasePermission):
    """Object-level permission enforcing organization matching."""
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
