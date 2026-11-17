from django.contrib import admin
from .models import Organization, OrganizationAttendancePolicy, OrganizationProvisioningPolicy


class OrganizationProvisioningPolicyInline(admin.StackedInline):
    model = OrganizationProvisioningPolicy
    can_delete = False
    verbose_name = "Student Provisioning & Credential Policy"
    verbose_name_plural = "Student Provisioning & Credential Policy (Onboarding Rules)"
    fieldsets = (
        ("Email & Identity Defaults", {
            "fields": (
                ("student_email_domain", "default_academic_level", "default_department"),
            ),
            "description": "Configure the institutional domain used for auto-generating emails and fallback academic levels."
        }),
        ("Password Generation & Security", {
            "fields": (
                ("password_strategy", "password_pattern"),
                ("auto_activate_accounts", "require_password_change"),
            ),
            "description": "Pattern template supports {student_id} and {org_slug}. Example: {student_id}#{org_slug}!"
        }),
    )


class OrganizationAttendancePolicyInline(admin.StackedInline):
    model = OrganizationAttendancePolicy
    can_delete = False
    verbose_name = "Attendance Policy & Thresholds"
    verbose_name_plural = "Attendance Policy & Thresholds (Dynamic Rules)"
    fieldsets = (
        ("Session Timing", {
            "fields": (
                ("default_session_duration_minutes", "late_after_minutes"),
            ),
            "description": "Configure how long sessions stay open and the grace period before check-ins count as LATE."
        }),
        ("Location & Geofencing Policies", {
            "fields": (
                ("allowed_radius_meters", "max_location_accuracy_meters"),
                ("location_max_age_seconds", "accuracy_tolerance_meters"),
            ),
            "description": "Configure the allowed distance, GPS accuracy rejection threshold, and coordinate freshness."
        }),
        ("Security & Staff Permissions", {
            "fields": (
                ("challenge_ttl_seconds",),
                ("allow_staff_custom_duration", "allow_staff_custom_radius"),
            ),
        }),
    )


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [OrganizationAttendancePolicyInline, OrganizationProvisioningPolicyInline]

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    has_add_permission = has_view_permission
    has_change_permission = has_view_permission
    has_delete_permission = has_view_permission
