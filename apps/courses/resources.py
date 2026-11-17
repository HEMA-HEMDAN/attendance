"""
django-import-export resources for Courses app.
"""

from import_export import fields
from django.core.exceptions import ValidationError
from apps.accounts.resources import OrgScopedModelResource
from apps.accounts.widgets import OrgForeignKeyWidget
from apps.courses.models import AcademicYear, Semester, Course, CourseOffering, Schedule, SessionType
from apps.staff.models import Doctor, TeachingAssistant
from apps.groups.models import Group
from apps.locations.models import AttendanceLocation


class AcademicYearResource(OrgScopedModelResource):
    class Meta(OrgScopedModelResource.Meta):
        model = AcademicYear
        import_id_fields = ['name']
        fields = ['name', 'start_date', 'end_date', 'is_active']
        export_order = ['name', 'start_date', 'end_date', 'is_active']

    def get_instance(self, instance_loader, row):
        return self.get_queryset().filter(name=row.get('name')).first()

    def init_instance(self, row=None):
        instance = super().init_instance(row=row)
        if self.organization:
            instance.organization = self.organization
        return instance


class SemesterResource(OrgScopedModelResource):
    academic_year = fields.Field(
        column_name='academic_year',
        attribute='academic_year',
        widget=OrgForeignKeyWidget(AcademicYear, 'name')
    )

    class Meta(OrgScopedModelResource.Meta):
        model = Semester
        fields = ['academic_year', 'name', 'start_date', 'end_date', 'is_active']
        export_order = ['academic_year', 'name', 'start_date', 'end_date', 'is_active']

    def get_instance(self, instance_loader, row):
        year_name = row.get('academic_year')
        sem_name = row.get('name')
        if not year_name or not sem_name:
            return None
        year = AcademicYear.objects.filter(organization=self.organization, name=year_name).first()
        if not year:
            return None
        return Semester.objects.filter(academic_year=year, name=sem_name).first()

    def before_save_instance(self, instance, row, **kwargs):
        super().before_save_instance(instance, row, **kwargs)
        if instance.academic_year and instance.academic_year.organization_id != self.organization.id:
            raise ValidationError("Referenced AcademicYear belongs to a different organization.")
        instance.organization = self.organization


class CourseResource(OrgScopedModelResource):
    class Meta(OrgScopedModelResource.Meta):
        model = Course
        import_id_fields = ['code']
        fields = ['code', 'name', 'department']
        export_order = ['code', 'name', 'department']

    def get_instance(self, instance_loader, row):
        return self.get_queryset().filter(code=row.get('code')).first()

    def init_instance(self, row=None):
        instance = super().init_instance(row=row)
        if self.organization:
            instance.organization = self.organization
        return instance


class CourseOfferingResource(OrgScopedModelResource):
    course_code = fields.Field(column_name='course_code')
    academic_year = fields.Field(column_name='academic_year')
    semester = fields.Field(column_name='semester')
    doctor_email = fields.Field(column_name='doctor_email')
    status = fields.Field(attribute='status', column_name='status')

    class Meta(OrgScopedModelResource.Meta):
        model = CourseOffering
        fields = ['course_code', 'academic_year', 'semester', 'doctor_email', 'status']
        export_order = ['course_code', 'academic_year', 'semester', 'doctor_email', 'status']

    def get_instance(self, instance_loader, row):
        course_code = row.get('course_code')
        year_name = row.get('academic_year')
        sem_name = row.get('semester')
        if not (course_code and year_name and sem_name):
            return None

        return CourseOffering.objects.filter(
            course__organization=self.organization,
            course__code=course_code,
            academic_year__name=year_name,
            semester__name=sem_name
        ).first()

    def init_instance(self, row=None):
        return CourseOffering()

    def before_save_instance(self, instance, row, **kwargs):
        super().before_save_instance(instance, row, **kwargs)
        course_code = str(row.get('course_code', '')).strip()
        year_name = str(row.get('academic_year', '')).strip()
        sem_name = str(row.get('semester', '')).strip()
        doctor_email = str(row.get('doctor_email', '')).strip() if row.get('doctor_email') else None

        course = Course.objects.filter(organization=self.organization, code=course_code).first()
        if not course:
            raise ValidationError(f"Course '{course_code}' does not exist in this organization.")

        year = AcademicYear.objects.filter(organization=self.organization, name=year_name).first()
        if not year:
            raise ValidationError(f"Academic Year '{year_name}' does not exist in this organization.")

        semester = Semester.objects.filter(academic_year=year, name=sem_name).first()
        if not semester:
            raise ValidationError(f"Semester '{sem_name}' does not exist under Academic Year '{year_name}'.")

        doctor = None
        if doctor_email:
            doctor = Doctor.objects.filter(organization=self.organization, user__email=doctor_email).first()
            if not doctor:
                raise ValidationError(f"Doctor with email '{doctor_email}' does not exist in this organization.")

        instance.course = course
        instance.academic_year = year
        instance.semester = semester
        instance.doctor = doctor
        if row.get('status'):
            instance.status = row['status']

    def dehydrate_course_code(self, obj):
        return obj.course.code if obj.course else ''

    def dehydrate_academic_year(self, obj):
        return obj.academic_year.name if obj.academic_year else ''

    def dehydrate_semester(self, obj):
        return obj.semester.name if obj.semester else ''

    def dehydrate_doctor_email(self, obj):
        return obj.doctor.user.email if (obj.doctor and obj.doctor.user) else ''


class ScheduleResource(OrgScopedModelResource):
    course_code = fields.Field(column_name='course_code')
    academic_year = fields.Field(column_name='academic_year')
    semester = fields.Field(column_name='semester')
    session_type = fields.Field(column_name='session_type', attribute='session_type')
    group_name = fields.Field(column_name='group_name')
    doctor_email = fields.Field(column_name='doctor_email')
    ta_email = fields.Field(column_name='ta_email')
    location_name = fields.Field(column_name='location_name')
    room_label = fields.Field(column_name='room_label', attribute='room_label')
    day_of_week = fields.Field(column_name='day_of_week', attribute='day_of_week')
    start_time = fields.Field(column_name='start_time', attribute='start_time')
    end_time = fields.Field(column_name='end_time', attribute='end_time')
    is_active = fields.Field(column_name='is_active', attribute='is_active')

    class Meta(OrgScopedModelResource.Meta):
        model = Schedule
        fields = [
            'course_code', 'academic_year', 'semester', 'session_type', 'group_name',
            'doctor_email', 'ta_email', 'location_name', 'room_label', 'day_of_week',
            'start_time', 'end_time', 'is_active'
        ]
        export_order = fields

    def get_instance(self, instance_loader, row):
        course_code = row.get('course_code')
        year_name = row.get('academic_year')
        sem_name = row.get('semester')
        session_type = row.get('session_type')
        day_of_week = row.get('day_of_week')
        start_time = row.get('start_time')
        group_name = row.get('group_name')

        if not (course_code and year_name and sem_name and session_type and day_of_week and start_time):
            return None

        offering = CourseOffering.objects.filter(
            course__organization=self.organization,
            course__code=course_code,
            academic_year__name=year_name,
            semester__name=sem_name
        ).first()
        if not offering:
            return None

        qs = Schedule.objects.filter(
            course_offering=offering,
            session_type=session_type,
            day_of_week=day_of_week,
            start_time=start_time
        )
        if group_name:
            qs = qs.filter(group__name=group_name)
        else:
            qs = qs.filter(group__isnull=True)

        return qs.first()

    def init_instance(self, row=None):
        return Schedule()

    def before_save_instance(self, instance, row, **kwargs):
        super().before_save_instance(instance, row, **kwargs)
        course_code = str(row.get('course_code', '')).strip()
        year_name = str(row.get('academic_year', '')).strip()
        sem_name = str(row.get('semester', '')).strip()
        group_name = str(row.get('group_name', '')).strip() if row.get('group_name') else None
        doc_email = str(row.get('doctor_email', '')).strip() if row.get('doctor_email') else None
        ta_email = str(row.get('ta_email', '')).strip() if row.get('ta_email') else None
        loc_name = str(row.get('location_name', '')).strip() if row.get('location_name') else None

        offering = CourseOffering.objects.filter(
            course__organization=self.organization,
            course__code=course_code,
            academic_year__name=year_name,
            semester__name=sem_name
        ).first()
        if not offering:
            raise ValidationError(f"Course Offering '{course_code} ({year_name} - {sem_name})' not found.")

        group = None
        if group_name:
            group = Group.objects.filter(course_offering=offering, name=group_name).first()
            if not group:
                raise ValidationError(f"Group '{group_name}' not found under offering '{course_code}'.")

        doctor = None
        if doc_email:
            doctor = Doctor.objects.filter(organization=self.organization, user__email=doc_email).first()
            if not doctor:
                raise ValidationError(f"Doctor '{doc_email}' not found in this organization.")

        ta = None
        if ta_email:
            ta = TeachingAssistant.objects.filter(organization=self.organization, user__email=ta_email).first()
            if not ta:
                raise ValidationError(f"Teaching Assistant '{ta_email}' not found in this organization.")

        location = None
        if loc_name:
            location = AttendanceLocation.objects.filter(organization=self.organization, name=loc_name).first()
            if not location:
                raise ValidationError(f"Attendance Location '{loc_name}' not found in this organization.")

        instance.course_offering = offering
        instance.group = group
        instance.doctor = doctor
        instance.teaching_assistant = ta
        instance.location = location

    def dehydrate_course_code(self, obj):
        return obj.course_offering.course.code if obj.course_offering and obj.course_offering.course else ''

    def dehydrate_academic_year(self, obj):
        return obj.course_offering.academic_year.name if obj.course_offering and obj.course_offering.academic_year else ''

    def dehydrate_semester(self, obj):
        return obj.course_offering.semester.name if obj.course_offering and obj.course_offering.semester else ''

    def dehydrate_group_name(self, obj):
        return obj.group.name if obj.group else ''

    def dehydrate_doctor_email(self, obj):
        return obj.doctor.user.email if obj.doctor and obj.doctor.user else ''

    def dehydrate_ta_email(self, obj):
        return obj.teaching_assistant.user.email if obj.teaching_assistant and obj.teaching_assistant.user else ''

    def dehydrate_location_name(self, obj):
        return obj.location.name if obj.location else ''
