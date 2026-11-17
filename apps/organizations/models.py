"""
Organizations app.

An Organization is the top-level tenant. All data is scoped to an organization.
"""

from django.db import models


class OrganizationStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    SUSPENDED = 'SUSPENDED', 'Suspended'
    ARCHIVED = 'ARCHIVED', 'Archived'


class Organization(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, max_length=100)
    timezone = models.CharField(
        max_length=50,
        default='Africa/Cairo',
        help_text='Timezone name (e.g. Africa/Cairo, UTC, America/New_York)',
    )
    status = models.CharField(
        max_length=20,
        choices=OrganizationStatus.choices,
        default=OrganizationStatus.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'organizations'

    def __str__(self):
        return self.name

    def get_provisioning_policy(self):
        policy, _ = OrganizationProvisioningPolicy.objects.get_or_create(organization=self)
        return policy


class PasswordStrategy(models.TextChoices):
    FORMULA = 'FORMULA', 'Formula Template'
    RANDOM_TEMP = 'RANDOM_TEMP', 'Random Temporary Password'


class OrganizationProvisioningPolicy(models.Model):
    """
    Configurable student credential generation, email domain, and default onboarding rules.
    Admin-configurable per organization.
    """
    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name='provisioning_policy',
    )
    student_email_domain = models.CharField(
        max_length=100,
        default='fci.edu',
        help_text='Domain for auto-generating student emails (e.g. fci.edu, university.edu.eg)',
    )
    password_strategy = models.CharField(
        max_length=20,
        choices=PasswordStrategy.choices,
        default=PasswordStrategy.FORMULA,
        help_text='Strategy used to generate initial student login passwords',
    )
    password_pattern = models.CharField(
        max_length=100,
        default='{student_id}#{org_slug}!',
        help_text='Pattern when using Formula (supports {student_id}, {org_slug})',
    )
    default_department = models.CharField(
        max_length=100,
        default='General',
        blank=True,
        help_text='Default department assigned if omitted in import files',
    )
    default_academic_level = models.CharField(
        max_length=50,
        default='Level 1',
        blank=True,
        help_text='Default academic level assigned if omitted in import files',
    )
    auto_activate_accounts = models.BooleanField(
        default=True,
        help_text='Whether newly imported student accounts are immediately active',
    )
    require_password_change = models.BooleanField(
        default=False,
        help_text='Force student to change their password upon their first login',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'organization_provisioning_policies'
        verbose_name = 'Provisioning Policy'
        verbose_name_plural = 'Provisioning Policies'

    def __str__(self):
        return f"Provisioning Policy for {self.organization.name}"


class OrganizationAttendancePolicy(models.Model):
    """
    Dynamic attendance policies and thresholds per organization.
    Admin-configurable — eliminates hardcoded constants from codebase.
    """
    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name='attendance_policy',
    )
    
    # Session timing
    default_session_duration_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Default lifetime for active attendance sessions in minutes (e.g. 45, 60, 90, 120)."
    )
    late_after_minutes = models.PositiveIntegerField(
        default=15,
        help_text="Minutes after session start before student check-ins are classified as LATE."
    )

    # Location & Geofencing thresholds
    allowed_radius_meters = models.FloatField(
        default=200.0,
        help_text="Default geofence radius around staff opening location in meters."
    )
    max_location_accuracy_meters = models.FloatField(
        default=200.0,
        help_text="Rejection threshold for GPS accuracy. Readings coarser than this value are rejected."
    )
    location_max_age_seconds = models.PositiveIntegerField(
        default=300,
        help_text="Maximum allowed age of opener GPS coordinates in seconds before considered stale."
    )
    accuracy_tolerance_meters = models.FloatField(
        default=75.0,
        help_text="Tolerance buffer added to radius for student devices with moderate GPS noise."
    )

    # Challenge / Security
    challenge_ttl_seconds = models.PositiveIntegerField(
        default=1000,
        help_text="TTL in seconds for cryptographic student check-in challenges."
    )

    # Permissions
    allow_staff_custom_duration = models.BooleanField(
        default=False,
        help_text="Whether Doctors/TAs can choose custom durations from the mobile app."
    )
    allow_staff_custom_radius = models.BooleanField(
        default=False,
        help_text="Whether Doctors/TAs can adjust the radius beyond the organization default."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'organization_attendance_policies'
        verbose_name = 'Attendance Policy'
        verbose_name_plural = 'Attendance Policies'

    def __str__(self):
        return f"Policy for {self.organization.name} (Duration: {self.default_session_duration_minutes}m, Radius: {self.allowed_radius_meters}m)"

