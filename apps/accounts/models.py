"""
Accounts app — custom User model with role-based access.

Roles:
  ADMIN   — Organization administrator
  TEACHER — Teacher within an organization
  STUDENT — Student within an organization

All users belong to exactly one organization.
"""

from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager


class Role(models.TextChoices):
    SUPERADMIN = 'SUPERADMIN', 'Superadmin'
    ADMIN = 'ADMIN', 'Admin'
    DOCTOR = 'DOCTOR', 'Doctor'
    TEACHING_ASSISTANT = 'TEACHING_ASSISTANT', 'Teaching Assistant'
    STUDENT = 'STUDENT', 'Student'


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', Role.ADMIN)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Central user model. Organization FK is nullable to allow superusers
    without an organization (system administrators).
    """

    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)

    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='users',
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    objects = UserManager()

    class Meta:
        db_table = 'users'
        indexes = [
            models.Index(fields=['organization', 'role']),
            models.Index(fields=['email']),
        ]

    def __str__(self):
        return f'{self.get_full_name()} <{self.email}>'

    def get_full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    @property
    def is_superadmin(self):
        return self.role == Role.SUPERADMIN

    @property
    def is_organization_admin(self):
        return self.role == Role.ADMIN

    @property
    def is_doctor(self):
        return self.role == Role.DOCTOR

    @property
    def is_teaching_assistant(self):
        return self.role == Role.TEACHING_ASSISTANT

    @property
    def is_student(self):
        return self.role == Role.STUDENT

    @property
    def is_staff_member(self):
        return self.role in (Role.SUPERADMIN, Role.ADMIN, Role.DOCTOR, Role.TEACHING_ASSISTANT)
