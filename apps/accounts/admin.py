"""
Enhanced Django Admin for Bio Attendance.

This is the primary management UI for organization admins.
Covers: students, teachers, groups, courses, devices, locations,
        attendance sessions/records, CSV import, and audit logs.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group

from .models import User


class OrgScopedAdminMixin:
    """
    Mixin that auto-scopes querysets to the logged-in user's organization.
    Superusers see everything.
    """

    org_field = 'organization'
    related_org_fields = {}

    def _organization_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(**{self.org_field: request.user.organization})

    def get_queryset(self, request):
        return self._organization_queryset(request)

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser and not change:
            setattr(obj, self.org_field, request.user.organization)
        super().save_model(request, obj, form, change)

    def has_view_permission(self, request, obj=None):
        if not super().has_view_permission(request, obj):
            return False
        return request.user.is_superuser or (
            request.user.role == 'ADMIN' and
            request.user.organization_id is not None and
            (obj is None or obj in self.get_queryset(request))
        )

    def has_change_permission(self, request, obj=None):
        if not super().has_change_permission(request, obj):
            return False
        return request.user.is_superuser or (
            request.user.role == 'ADMIN' and
            request.user.organization_id is not None and
            (obj is None or obj in self.get_queryset(request))
        )

    def has_delete_permission(self, request, obj=None):
        if not super().has_delete_permission(request, obj):
            return False
        return request.user.is_superuser or (
            request.user.role == 'ADMIN' and
            request.user.organization_id is not None and
            (obj is None or obj in self.get_queryset(request))
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if request.user.is_superuser or not hasattr(formfield, 'queryset'):
            return formfield
        model = db_field.remote_field.model
        if any(field.name == 'organization' for field in model._meta.fields):
            formfield.queryset = formfield.queryset.filter(organization=request.user.organization)
        lookup = self.related_org_fields.get(db_field.name)
        if lookup:
            formfield.queryset = formfield.queryset.filter(**{lookup: request.user.organization})
        return formfield


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['email', 'get_full_name', 'role', 'organization', 'is_active', 'created_at']
    list_filter = ['role', 'is_active', 'organization']
    search_fields = ['email', 'first_name', 'last_name']
    ordering = ['email']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name')}),
        ('Organization & Role', {'fields': ('organization', 'role')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'role', 'organization', 'password1', 'password2'),
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(organization=request.user.organization)

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    has_add_permission = has_view_permission
    has_change_permission = has_view_permission
    has_delete_permission = has_view_permission


try:
    admin.site.unregister(Group)
except admin.sites.NotRegistered:
    pass


@admin.register(Group)
class PlatformGroupAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    has_add_permission = has_view_permission
    has_change_permission = has_view_permission
    has_delete_permission = has_view_permission

