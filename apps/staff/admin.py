from django.contrib import admin
from apps.accounts.admin import OrgScopedAdminMixin
from .models import Doctor, TeachingAssistant


@admin.register(Doctor)
class DoctorAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    related_org_fields = {'user': 'organization'}
    list_display = ['title', 'get_full_name', 'email', 'department', 'organization']
    list_filter = ['organization', 'department']
    search_fields = ['user__first_name', 'user__last_name', 'user__email', 'department']

    def get_full_name(self, obj):
        return obj.user.get_full_name()
    get_full_name.short_description = 'Name'

    def email(self, obj):
        return obj.user.email


@admin.register(TeachingAssistant)
class TeachingAssistantAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    related_org_fields = {'user': 'organization'}
    list_display = ['get_full_name', 'email', 'department', 'organization']
    list_filter = ['organization', 'department']
    search_fields = ['user__first_name', 'user__last_name', 'user__email', 'department']

    def get_full_name(self, obj):
        return obj.user.get_full_name()
    get_full_name.short_description = 'Name'

    def email(self, obj):
        return obj.user.email
