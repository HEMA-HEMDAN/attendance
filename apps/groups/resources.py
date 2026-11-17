"""
django-import-export resources for Groups app.
"""

from import_export import fields
from django.core.exceptions import ValidationError
from apps.accounts.resources import OrgScopedModelResource
from apps.groups.models import Group
from apps.courses.models import CourseOffering
from apps.staff.models import TeachingAssistant


class GroupResource(OrgScopedModelResource):
    org_field_lookup = 'course_offering__course__organization'

    course_code = fields.Field(column_name='course_code')
    academic_year = fields.Field(column_name='academic_year')
    semester = fields.Field(column_name='semester')
    name = fields.Field(column_name='name', attribute='name')
    ta_email = fields.Field(column_name='ta_email')
    status = fields.Field(column_name='status', attribute='status')

    class Meta(OrgScopedModelResource.Meta):
        model = Group
        fields = ['course_code', 'academic_year', 'semester', 'name', 'ta_email', 'status']
        export_order = fields

    def get_instance(self, instance_loader, row):
        course_code = row.get('course_code')
        year_name = row.get('academic_year')
        sem_name = row.get('semester')
        group_name = row.get('name')

        if not (course_code and year_name and sem_name and group_name):
            return None

        offering = CourseOffering.objects.filter(
            course__organization=self.organization,
            course__code=course_code,
            academic_year__name=year_name,
            semester__name=sem_name
        ).first()
        if not offering:
            return None

        return Group.objects.filter(course_offering=offering, name=group_name).first()

    def init_instance(self, row=None):
        return Group()

    def before_save_instance(self, instance, row, **kwargs):
        super().before_save_instance(instance, row, **kwargs)
        course_code = str(row.get('course_code', '')).strip()
        year_name = str(row.get('academic_year', '')).strip()
        sem_name = str(row.get('semester', '')).strip()
        group_name = str(row.get('name', '')).strip()
        ta_email = str(row.get('ta_email', '')).strip() if row.get('ta_email') else None

        offering = CourseOffering.objects.filter(
            course__organization=self.organization,
            course__code=course_code,
            academic_year__name=year_name,
            semester__name=sem_name
        ).first()
        if not offering:
            raise ValidationError(f"Course Offering '{course_code} ({year_name} - {sem_name})' not found.")

        ta = None
        if ta_email:
            ta = TeachingAssistant.objects.filter(organization=self.organization, user__email=ta_email).first()
            if not ta:
                raise ValidationError(f"Teaching Assistant '{ta_email}' not found in this organization.")

        instance.course_offering = offering
        instance.name = group_name
        instance.teaching_assistant = ta
        if row.get('status'):
            instance.status = row['status']

    def dehydrate_course_code(self, obj):
        return obj.course_offering.course.code if obj.course_offering and obj.course_offering.course else ''

    def dehydrate_academic_year(self, obj):
        return obj.course_offering.academic_year.name if obj.course_offering and obj.course_offering.academic_year else ''

    def dehydrate_semester(self, obj):
        return obj.course_offering.semester.name if obj.course_offering and obj.course_offering.semester else ''

    def dehydrate_ta_email(self, obj):
        return obj.teaching_assistant.user.email if obj.teaching_assistant and obj.teaching_assistant.user else ''
