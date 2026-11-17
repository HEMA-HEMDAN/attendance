from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from apps.accounts.models import User


ORGANIZATION_ADMIN_GROUP = 'Organization Admin'

# Organization admins manage tenant data, but not tenants, permissions, or
# generated/security-sensitive attendance records.
ORGANIZATION_ADMIN_PERMISSIONS = {
    ('organizations', 'organization'): {'view'},
    ('students', 'student'): {'view', 'add', 'change', 'delete'},
    ('students', 'studentenrollment'): {'view', 'add', 'change', 'delete'},
    ('staff', 'doctor'): {'view', 'add', 'change', 'delete'},
    ('staff', 'teachingassistant'): {'view', 'add', 'change', 'delete'},
    ('courses', 'academicyear'): {'view', 'add', 'change', 'delete'},
    ('courses', 'semester'): {'view', 'add', 'change', 'delete'},
    ('courses', 'course'): {'view', 'add', 'change', 'delete'},
    ('courses', 'courseoffering'): {'view', 'add', 'change', 'delete'},
    ('courses', 'schedule'): {'view', 'add', 'change', 'delete'},
    ('courses', 'scheduleexception'): {'view', 'add', 'change', 'delete'},
    ('groups', 'group'): {'view', 'add', 'change', 'delete'},
    ('locations', 'attendancelocation'): {'view', 'add', 'change', 'delete'},
    ('devices', 'device'): {'view', 'change', 'delete'},
    ('attendance', 'sessionoccurrence'): {'view'},
    ('attendance', 'attendancesession'): {'view'},
    ('attendance', 'attendancerecord'): {'view'},
    ('attendance', 'devicechallenge'): {'view'},
    ('audit', 'auditlog'): {'view'},
}


def ensure_organization_admin_group():
    group, _ = Group.objects.get_or_create(name=ORGANIZATION_ADMIN_GROUP)
    permissions = []
    for (app_label, model_name), actions in ORGANIZATION_ADMIN_PERMISSIONS.items():
        model = next(
            (model for model in User._meta.apps.get_models()
             if model._meta.app_label == app_label and model._meta.model_name == model_name),
            None,
        )
        if model is None:
            continue
        content_type = ContentType.objects.get_for_model(model)
        permissions.extend(
            Permission.objects.filter(
                content_type=content_type,
                codename__in={f'{action}_{model_name}' for action in actions},
            )
        )
    group.permissions.set(permissions)
    return group


def configure_organization_admin(user):
    group = ensure_organization_admin_group()
    user.is_staff = True
    user.is_superuser = False
    user.groups.set([group])
    user.user_permissions.clear()
    user.save(update_fields=['is_staff', 'is_superuser'])
    return user