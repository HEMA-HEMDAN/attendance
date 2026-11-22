"""
Enhanced Django Admin for Bio Attendance.

This is the primary management UI for organization admins.
Covers: students, teachers, groups, courses, devices, locations,
        attendance sessions/records, CSV import, and audit logs.
"""

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import FieldDoesNotExist
from import_export.admin import ImportExportModelAdmin
from import_export.forms import ImportForm, ConfirmImportForm

from apps.organizations.models import Organization, OrganizationStatus
from .models import User, Role


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

    def get_exclude(self, request, obj=None):
        exclude = list(super().get_exclude(request, obj) or [])
        if not request.user.is_superuser:
            try:
                self.model._meta.get_field('organization')
            except FieldDoesNotExist:
                pass
            else:
                if 'organization' not in exclude:
                    exclude.append('organization')
        return exclude

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

    def has_add_permission(self, request):
        if not super().has_add_permission(request):
            return False
        return request.user.is_superuser or (
            request.user.role == 'ADMIN' and
            request.user.organization_id is not None
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


class SuperadminImportForm(ImportForm):
    organization = forms.ModelChoiceField(
        queryset=Organization.objects.filter(status=OrganizationStatus.ACTIVE),
        required=True,
        help_text="Select the target organization for this import."
    )


class SuperadminConfirmImportForm(ConfirmImportForm):
    organization = forms.ModelChoiceField(
        queryset=Organization.objects.filter(status=OrganizationStatus.ACTIVE),
        widget=forms.HiddenInput(),
        required=True
    )


class TenantScopedImportExportAdmin(OrgScopedAdminMixin, ImportExportModelAdmin):
    """
    Base Admin combining multi-tenant row/field scoping with django-import-export.
    Enforces tenant boundaries, granular permissions, atomic rollback, and superadmin target org preservation.
    """
    import_enabled = True
    export_enabled = True

    def has_import_permission(self, request):
        # 1. Reject categorically if model is export-only
        if not self.import_enabled:
            return False
        # 2. Superadmin has global import access (target organization selected in form)
        if request.user.is_superuser:
            return True
        # 3. Model-level authorization: importing creates and modifies records;
        # user must possess standard model add AND change permissions.
        if not (self.has_add_permission(request) and self.has_change_permission(request)):
            return False
        # 4. Tenant binding: must be an active admin with an assigned organization
        return request.user.role == Role.ADMIN and request.user.organization_id is not None

    def has_export_permission(self, request):
        if not self.export_enabled:
            return False
        if request.user.is_superuser:
            return True
        # Exporting accesses model records; user must possess view permission.
        if not self.has_view_permission(request):
            return False
        return request.user.role == Role.ADMIN and request.user.organization_id is not None

    def get_import_form_class(self, request):
        if request.user.is_superuser:
            return SuperadminImportForm
        return super().get_import_form_class(request)

    def get_confirm_form_class(self, request):
        if request.user.is_superuser:
            return SuperadminConfirmImportForm
        return super().get_confirm_form_class(request)

    def get_confirm_form_initial(self, request, import_form):
        initial = super().get_confirm_form_initial(request, import_form)
        if request.user.is_superuser and import_form and hasattr(import_form, 'cleaned_data') and 'organization' in import_form.cleaned_data:
            org = import_form.cleaned_data['organization']
            initial['organization'] = org.pk if hasattr(org, 'pk') else org
        return initial

    def get_import_resource_kwargs(self, request, **kwargs):
        resource_kwargs = super().get_import_resource_kwargs(request, **kwargs)
        if request.user.is_superuser:
            form = kwargs.get('form')
            selected_org = None
            if form and getattr(form, 'is_bound', False) and form.is_valid():
                selected_org = form.cleaned_data.get('organization')
            if selected_org is None and request.POST and 'organization' in request.POST:
                try:
                    selected_org = Organization.objects.filter(status=OrganizationStatus.ACTIVE).get(pk=request.POST['organization'])
                except (Organization.DoesNotExist, ValueError):
                    pass
            resource_kwargs['organization'] = selected_org
            resource_kwargs['is_superuser'] = True
        else:
            resource_kwargs['organization'] = request.user.organization
            resource_kwargs['is_superuser'] = False
        return resource_kwargs

    def get_export_resource_kwargs(self, request, **kwargs):
        resource_kwargs = super().get_export_resource_kwargs(request, **kwargs)
        if request.user.is_superuser:
            resource_kwargs['organization'] = None
            resource_kwargs['is_superuser'] = True
        else:
            resource_kwargs['organization'] = request.user.organization
            resource_kwargs['is_superuser'] = False
        return resource_kwargs

    def get_import_data_kwargs(self, **kwargs):
        imp_kwargs = super().get_import_data_kwargs(**kwargs)
        imp_kwargs['rollback_on_validation_errors'] = True
        return imp_kwargs



@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['email', 'get_full_name', 'role', 'organization', 'is_active', 'created_at']
    list_filter = ['role', 'is_active', 'organization']
    search_fields = ['email', 'first_name', 'last_name']
    autocomplete_fields = ['organization']
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

