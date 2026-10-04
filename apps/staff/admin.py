from django.contrib import admin
from apps.accounts.admin import OrgScopedAdminMixin
from .models import Doctor, TeachingAssistant


from apps.courses.models import CourseOffering
from apps.groups.models import Group


class CourseOfferingInline(admin.TabularInline):
    model = CourseOffering
    extra = 1
    autocomplete_fields = ['course', 'academic_year', 'semester']
    verbose_name = 'Taught Course Offering'
    verbose_name_plural = 'Taught Course Offerings'


class AssignedGroupInline(admin.TabularInline):
    model = Group
    extra = 1
    autocomplete_fields = ['course_offering']
    verbose_name = 'Assigned Lab Group'
    verbose_name_plural = 'Assigned Lab Groups'


@admin.register(Doctor)
class DoctorAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    related_org_fields = {'user': 'organization'}
    list_display = ['title', 'get_full_name', 'email', 'department', 'organization']
    list_filter = ['organization', 'department']
    search_fields = ['user__first_name', 'user__last_name', 'user__email', 'department']
    autocomplete_fields = ['user', 'organization']
    inlines = [CourseOfferingInline]

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
    autocomplete_fields = ['user', 'organization']
    inlines = [AssignedGroupInline]

    def get_full_name(self, obj):
        return obj.user.get_full_name()
    get_full_name.short_description = 'Name'

    def email(self, obj):
        return obj.user.email
