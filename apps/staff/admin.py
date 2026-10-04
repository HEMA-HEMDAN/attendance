from django.contrib import admin
from apps.accounts.admin import OrgScopedAdminMixin
from .models import Doctor, TeachingAssistant


from apps.courses.models import CourseOffering, Schedule
from apps.groups.models import Group


from apps.courses.forms import ScheduleAdminForm
from apps.locations.models import AttendanceLocation


class CourseOfferingInline(admin.TabularInline):
    model = CourseOffering
    extra = 1
    show_change_link = True
    autocomplete_fields = ['course', 'academic_year', 'semester']
    verbose_name = 'Taught Course Offering'
    verbose_name_plural = 'Taught Course Offerings'


class DoctorScheduleInline(admin.TabularInline):
    model = Schedule
    form = ScheduleAdminForm
    fk_name = 'doctor'
    extra = 1
    show_change_link = True
    verbose_name = 'Doctor Schedule'
    verbose_name_plural = 'Doctor Schedules (All-in-One)'

    class Media:
        js = ('admin/js/schedule_group_filter.js',)

    def get_formset(self, request, obj=None, **kwargs):
        request._editing_doctor = obj
        return super().get_formset(request, obj, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        doctor = getattr(request, '_editing_doctor', None)
        if db_field.name == 'course_offering':
            if doctor:
                kwargs['queryset'] = CourseOffering.objects.filter(doctor=doctor)
            else:
                kwargs['queryset'] = CourseOffering.objects.none()
        elif db_field.name == 'group':
            if doctor:
                kwargs['queryset'] = Group.objects.filter(course_offering__doctor=doctor)
            else:
                kwargs['queryset'] = Group.objects.none()
        elif db_field.name == 'location':
            if doctor:
                kwargs['queryset'] = AttendanceLocation.objects.filter(organization=doctor.organization)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class AssignedGroupInline(admin.TabularInline):
    model = Group
    extra = 1
    show_change_link = True
    autocomplete_fields = ['course_offering']
    verbose_name = 'Assigned Lab Group'
    verbose_name_plural = 'Assigned Lab Groups'


class TAScheduleInline(admin.TabularInline):
    model = Schedule
    form = ScheduleAdminForm
    fk_name = 'teaching_assistant'
    extra = 1
    show_change_link = True
    verbose_name = 'TA Schedule'
    verbose_name_plural = 'TA Schedules (All-in-One)'

    class Media:
        js = ('admin/js/schedule_group_filter.js',)

    def get_formset(self, request, obj=None, **kwargs):
        request._editing_ta = obj
        return super().get_formset(request, obj, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        ta = getattr(request, '_editing_ta', None)
        if db_field.name == 'group':
            if ta:
                kwargs['queryset'] = Group.objects.filter(teaching_assistant=ta)
            else:
                kwargs['queryset'] = Group.objects.none()
        elif db_field.name == 'course_offering':
            if ta:
                kwargs['queryset'] = CourseOffering.objects.filter(groups__teaching_assistant=ta).distinct()
            else:
                kwargs['queryset'] = CourseOffering.objects.none()
        elif db_field.name == 'location':
            if ta:
                kwargs['queryset'] = AttendanceLocation.objects.filter(organization=ta.organization)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Doctor)
class DoctorAdmin(OrgScopedAdminMixin, admin.ModelAdmin):
    related_org_fields = {'user': 'organization'}
    list_display = ['title', 'get_full_name', 'email', 'department', 'organization']
    list_filter = ['organization', 'department']
    search_fields = ['user__first_name', 'user__last_name', 'user__email', 'department']
    autocomplete_fields = ['user', 'organization']
    inlines = [CourseOfferingInline, DoctorScheduleInline]

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
    inlines = [AssignedGroupInline, TAScheduleInline]

    def get_full_name(self, obj):
        return obj.user.get_full_name()
    get_full_name.short_description = 'Name'

    def email(self, obj):
        return obj.user.email
