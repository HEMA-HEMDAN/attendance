import pytest
from django.contrib import admin
from apps.accounts.models import User
from apps.students.models import Student, StudentEnrollment
from apps.staff.models import Doctor, TeachingAssistant
from apps.courses.models import Course, CourseOffering, Schedule, ScheduleException, AcademicYear, Semester
from apps.groups.models import Group
from apps.attendance.models import SessionOccurrence, AttendanceSession, AttendanceRecord, DeviceChallenge
from apps.devices.models import Device
from apps.locations.models import AttendanceLocation
from apps.audit.models import AuditLog


@pytest.mark.django_db
class TestDjangoAdminAutocompleteAndSearch:
    def test_admin_autocomplete_fields_registered(self):
        """Verify that all target ModelAdmins have autocomplete_fields configured for foreign keys."""
        student_admin = admin.site._registry[Student]
        assert 'user' in student_admin.autocomplete_fields
        assert 'organization' in student_admin.autocomplete_fields

        enrollment_admin = admin.site._registry[StudentEnrollment]
        assert 'student' in enrollment_admin.autocomplete_fields
        assert 'course_offering' in enrollment_admin.autocomplete_fields
        assert 'group' in enrollment_admin.autocomplete_fields

        doctor_admin = admin.site._registry[Doctor]
        assert 'user' in doctor_admin.autocomplete_fields

        ta_admin = admin.site._registry[TeachingAssistant]
        assert 'user' in ta_admin.autocomplete_fields

        offering_admin = admin.site._registry[CourseOffering]
        assert 'course' in offering_admin.autocomplete_fields
        assert 'doctor' in offering_admin.autocomplete_fields

        group_admin = admin.site._registry[Group]
        assert 'course_offering' in group_admin.autocomplete_fields
        assert 'teaching_assistant' in group_admin.autocomplete_fields

        schedule_admin = admin.site._registry[Schedule]
        assert 'course_offering' in schedule_admin.autocomplete_fields

        attendance_session_admin = admin.site._registry[AttendanceSession]
        assert 'occurrence' in attendance_session_admin.autocomplete_fields

        record_admin = admin.site._registry[AttendanceRecord]
        assert 'student' in record_admin.autocomplete_fields
        assert 'session' in record_admin.autocomplete_fields

        device_admin = admin.site._registry[Device]
        assert 'student' in device_admin.autocomplete_fields

    def test_referenced_models_have_search_fields(self):
        """Verify that all referenced models define search_fields as required by Django autocomplete."""
        user_admin = admin.site._registry[User]
        assert user_admin.search_fields

        student_admin = admin.site._registry[Student]
        assert student_admin.search_fields

        course_admin = admin.site._registry[Course]
        assert course_admin.search_fields

        offering_admin = admin.site._registry[CourseOffering]
        assert offering_admin.search_fields

        group_admin = admin.site._registry[Group]
        assert group_admin.search_fields

        ay_admin = admin.site._registry[AcademicYear]
        assert ay_admin.search_fields

        sem_admin = admin.site._registry[Semester]
        assert sem_admin.search_fields
