"""
Enhanced Django Admin for Bio Attendance.

This is the primary management UI for organization admins.
Covers: students, teachers, groups, courses, devices, locations,
        attendance sessions/records, CSV import, and audit logs.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from django.urls import path
from django.shortcuts import redirect, render
from django.contrib import messages
from django.http import HttpResponse
import csv
import io

from .models import User


class OrgScopedAdminMixin:
    """
    Mixin that auto-scopes querysets to the logged-in user's organization.
    Superusers see everything.
    """

    org_field = 'organization'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(**{self.org_field: request.user.organization})

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser and not change:
            setattr(obj, self.org_field, request.user.organization)
        super().save_model(request, obj, form, change)


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
