import io
import csv
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from apps.accounts.models import User, Role
from apps.organizations.models import Organization, OrganizationProvisioningPolicy, PasswordStrategy
from apps.courses.models import AcademicYear, Semester, Course, CourseOffering
from apps.groups.models import Group
from apps.students.models import Student, StudentEnrollment
from apps.students.services.bulk_importer import BulkStudentImporterService
from apps.students.services.bulk_enrollment import BulkEnrollmentActionService
from apps.students.services.template_builder import StudentTemplateBuilder


class BulkImportAndEnrollmentTestCase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="FCI Damanhour", slug="fci-damanhour")
        self.policy = self.org.get_provisioning_policy()
        self.policy.student_email_domain = "fci.edu"
        self.policy.password_pattern = "{student_id}#{org_slug}!"
        self.policy.save()

        self.admin_user = User.objects.create_user(
            email="admin@fci.edu",
            password="adminpassword123",
            first_name="Admin",
            last_name="User",
            role=Role.ADMIN,
            organization=self.org
        )

        self.year = AcademicYear.objects.create(
            organization=self.org,
            name="2026/2027",
            start_date="2026-08-01",
            end_date="2027-07-31",
            is_active=True
        )
        self.semester = Semester.objects.create(
            organization=self.org,
            academic_year=self.year,
            name="Term 1",
            start_date="2026-08-01",
            end_date="2027-01-31",
            is_active=True
        )
        self.course_ai = Course.objects.create(
            organization=self.org,
            code="AI101",
            name="Introduction to Artificial Intelligence",
            department="AI"
        )
        self.course_math = Course.objects.create(
            organization=self.org,
            code="MATH101",
            name="Calculus I",
            department="General"
        )
        self.offering_ai = CourseOffering.objects.create(
            course=self.course_ai,
            academic_year=self.year,
            semester=self.semester
        )
        self.offering_math = CourseOffering.objects.create(
            course=self.course_math,
            academic_year=self.year,
            semester=self.semester
        )
        self.group_ai_sec1 = Group.objects.create(
            course_offering=self.offering_ai,
            name="Section 1"
        )
        self.group_ai_sec2 = Group.objects.create(
            course_offering=self.offering_ai,
            name="Section 2"
        )

    def test_organization_provisioning_policy_defaults(self):
        self.assertEqual(self.policy.student_email_domain, "fci.edu")
        self.assertEqual(self.policy.password_strategy, PasswordStrategy.FORMULA)
        self.assertEqual(self.policy.password_pattern, "{student_id}#{org_slug}!")

    def test_bulk_importer_validate_and_atomic_execution(self):
        # Create sample CSV with Arabic names and section numbers
        csv_content = (
            "student_id,full_name,department,academic_level,section\n"
            "26140001,إبراهيم أشرف حسن,AI,Level 1,1\n"
            "26140002,سارة حسن السيد,AI,Level 1,2\n"
        ).encode('utf-8-sig')

        uploaded = SimpleUploadedFile("students.csv", csv_content, content_type="text/csv")

        # 1. Validate & Stage
        staged = BulkStudentImporterService.validate_and_stage(
            uploaded_file=uploaded,
            organization=self.org,
            selected_offering_ids=[self.offering_ai.id, self.offering_math.id]
        )

        self.assertEqual(len(staged['valid_rows']), 2)
        self.assertEqual(len(staged['existing_rows']), 0)
        self.assertEqual(len(staged['invalid_rows']), 0)
        self.assertEqual(len(staged['selected_offerings']), 2)

        # 2. Execute Import
        created, updated, enrollments = BulkStudentImporterService.execute_import(
            staged_data=staged,
            organization=self.org,
            admin_user=self.admin_user
        )

        self.assertEqual(created, 2)
        self.assertEqual(updated, 0)
        # 2 students x 2 courses = 4 enrollments
        self.assertEqual(enrollments, 4)

        # Verify Database Records
        student1 = Student.objects.get(student_id="26140001", organization=self.org)
        self.assertEqual(student1.user.email, "26140001@fci.edu")
        self.assertEqual(student1.user.first_name, "إبراهيم")
        self.assertEqual(student1.user.last_name, "أشرف حسن")
        self.assertTrue(student1.user.check_password("26140001#fci-damanhour!"))

        # Verify Group Mappings
        enr1_ai = StudentEnrollment.objects.get(student=student1, course_offering=self.offering_ai)
        self.assertEqual(enr1_ai.group, self.group_ai_sec1)

        enr1_math = StudentEnrollment.objects.get(student=student1, course_offering=self.offering_math)
        self.assertIsNone(enr1_math.group)  # MATH101 has no lab groups

        student2 = Student.objects.get(student_id="26140002", organization=self.org)
        enr2_ai = StudentEnrollment.objects.get(student=student2, course_offering=self.offering_ai)
        self.assertEqual(enr2_ai.group, self.group_ai_sec2)

    def test_bulk_importer_idempotent_reenrollment(self):
        # First import
        csv_1 = (
            "student_id,full_name,department,academic_level,section\n"
            "26140099,علي محمود,CS,Level 1,1\n"
        ).encode('utf-8-sig')
        file1 = SimpleUploadedFile("students1.csv", csv_1, content_type="text/csv")
        staged1 = BulkStudentImporterService.validate_and_stage(file1, self.org, [self.offering_ai.id])
        BulkStudentImporterService.execute_import(staged1, self.org, self.admin_user)

        self.assertEqual(Student.objects.filter(student_id="26140099").count(), 1)
        original_user_id = Student.objects.get(student_id="26140099").user_id

        # Second import (student advancing or enrolling in new course MATH101)
        csv_2 = (
            "student_id,full_name,department,academic_level,section\n"
            "26140099,علي محمود,CS,Level 2,1\n"
        ).encode('utf-8-sig')
        file2 = SimpleUploadedFile("students2.csv", csv_2, content_type="text/csv")
        staged2 = BulkStudentImporterService.validate_and_stage(file2, self.org, [self.offering_math.id])

        self.assertEqual(len(staged2['valid_rows']), 0)
        self.assertEqual(len(staged2['existing_rows']), 1)

        created, updated, enrollments = BulkStudentImporterService.execute_import(staged2, self.org, self.admin_user)
        self.assertEqual(created, 0)
        self.assertEqual(updated, 1)
        self.assertEqual(enrollments, 1)

        # Check that user ID is identical (preserved) and academic level updated
        student = Student.objects.get(student_id="26140099")
        self.assertEqual(student.user_id, original_user_id)
        self.assertEqual(student.academic_level, "Level 2")
        self.assertEqual(student.enrollments.count(), 2)

    def test_bulk_enrollment_action_service(self):
        # Create 3 students
        students = []
        for i in range(1, 4):
            u = User.objects.create_user(
                email=f"stu{i}@fci.edu",
                password="pass",
                first_name=f"Stu{i}",
                last_name="Test",
                role=Role.STUDENT,
                organization=self.org
            )
            s = Student.objects.create(
                user=u,
                organization=self.org,
                student_id=f"2614001{i}",
                academic_level="Level 1"
            )
            students.append(s)

        # Execute bulk enrollment via action service
        total, created, updated = BulkEnrollmentActionService.execute_enrollment(
            student_queryset=Student.objects.filter(id__in=[s.id for s in students]),
            offering_ids=[self.offering_ai.id, self.offering_math.id],
            strategy='LECTURE_ONLY',
            organization=self.org
        )

        self.assertEqual(total, 3)
        self.assertEqual(created, 6)
        self.assertEqual(StudentEnrollment.objects.filter(student__in=students).count(), 6)

    def test_template_builder(self):
        response = StudentTemplateBuilder.generate_template(self.org)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        self.assertIn("student_import_template_fci-damanhour.xlsx", response['Content-Disposition'])
