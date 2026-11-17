"""
Enterprise Bulk Student Importer Service.

Features:
  - Multi-table atomic creation: User + Student + StudentEnrollments + Group assignments
  - Supports Excel (.xlsx) and CSV (utf-8-sig / Arabic encoding)
  - Reads OrganizationProvisioningPolicy for email domain and password generation
  - Two-phase execution: Pre-flight validation & dry-run -> Session-staged atomic commit
  - Graceful re-enrollment (upsert) for existing students without account conflicts
"""

import csv
import io
import re
import uuid
import secrets
from collections import defaultdict
from django.db import transaction
from django.core.exceptions import ValidationError

import openpyxl

from apps.accounts.models import User, Role
from apps.courses.models import CourseOffering
from apps.groups.models import Group
from apps.students.models import Student, StudentEnrollment


class BulkStudentImporterService:
    @staticmethod
    def split_name(full_name):
        parts = (full_name or '').strip().split()
        if not parts:
            return 'Student', '-'
        if len(parts) == 1:
            return parts[0], '-'
        return parts[0], ' '.join(parts[1:])

    @staticmethod
    def normalize_section(raw_section):
        if not raw_section:
            return None
        raw_str = str(raw_section).strip()
        # Look for digit first
        digits = re.findall(r'\d+', raw_str)
        if digits:
            return digits[0]
        return raw_str

    @classmethod
    def parse_file(cls, uploaded_file):
        """Parses .xlsx or .csv and yields normalized dictionaries."""
        filename = uploaded_file.name.lower()
        rows = []

        if filename.endswith('.xlsx'):
            wb = openpyxl.load_workbook(uploaded_file, data_only=True)
            ws = wb.active
            headers = None
            for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
                if not any(row):
                    continue
                if headers is None:
                    headers = [str(c).strip().lower().replace(' ', '_') if c is not None else '' for c in row]
                    continue
                row_dict = {}
                for idx, cell in enumerate(row):
                    if idx < len(headers) and headers[idx]:
                        val = str(cell).strip() if cell is not None else ''
                        if val.endswith('.0') and val[:-2].isdigit():
                            val = val[:-2]
                        row_dict[headers[idx]] = val
                if any(row_dict.values()):
                    row_dict['_row_num'] = row_idx
                    rows.append(row_dict)

        elif filename.endswith('.csv'):
            content = uploaded_file.read()
            for encoding in ('utf-8-sig', 'utf-8', 'windows-1256'):
                try:
                    text = content.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                text = content.decode('utf-8', errors='replace')

            reader = csv.DictReader(io.StringIO(text))
            for row_idx, r in enumerate(reader, start=2):
                clean_row = {}
                for k, v in r.items():
                    if k is not None:
                        clean_row[k.strip().lower().replace(' ', '_')] = (v or '').strip()
                if any(clean_row.values()):
                    clean_row['_row_num'] = row_idx
                    rows.append(clean_row)
        else:
            raise ValidationError("Please upload an Excel (.xlsx) or CSV (.csv) file.")

        return rows

    @classmethod
    def validate_and_stage(cls, uploaded_file, organization, selected_offering_ids=None):
        """
        Validates parsed rows against database constraints and staging rules.
        Returns:
            staging_token, valid_rows, existing_rows, invalid_rows, selected_offerings
        """
        rows = cls.parse_file(uploaded_file)
        if not rows:
            raise ValidationError("The uploaded spreadsheet is empty.")

        policy = organization.get_provisioning_policy()
        selected_offering_ids = [int(i) for i in (selected_offering_ids or []) if str(i).isdigit()]
        selected_offerings = list(CourseOffering.objects.filter(
            id__in=selected_offering_ids,
            course__organization=organization
        ).select_related('course', 'academic_year', 'semester'))

        # Pre-fetch existing students in this org
        existing_students = {
            s.student_id: s for s in Student.objects.filter(organization=organization).select_related('user')
        }
        # Pre-fetch existing emails
        existing_emails = set(User.objects.values_list('email', flat=True))

        valid_rows = []
        existing_rows = []
        invalid_rows = []
        seen_file_ids = set()

        for r in rows:
            row_num = r.get('_row_num', '?')
            errors = []

            # Extract student ID
            student_id = (
                r.get('student_id') or r.get('student_code') or r.get('code') or r.get('id') or ''
            ).strip()
            # Extract name
            name = (
                r.get('full_name') or r.get('name') or r.get('student_name') or
                r.get('student_name_ar') or f"{r.get('first_name', '')} {r.get('last_name', '')}"
            ).strip()

            if not student_id:
                errors.append("Missing student ID / code")
            if not name or name == '-':
                errors.append("Missing student name")

            # Check duplicate within spreadsheet
            if student_id:
                if student_id in seen_file_ids:
                    errors.append(f"Duplicate student ID in file: {student_id}")
                seen_file_ids.add(student_id)

            # Department and level
            dept = r.get('department') or r.get('dept') or policy.default_department
            level = r.get('academic_level') or r.get('level') or policy.default_academic_level
            section = cls.normalize_section(r.get('section') or r.get('group') or '')
            phone = r.get('phone') or ''
            personal_email = r.get('personal_email') or ''
            custom_courses = [c.strip() for c in r.get('courses', '').split(',') if c.strip()]

            # Determine email
            email = r.get('email', '').strip()
            if not email and student_id:
                email = f"{student_id}@{policy.student_email_domain}"

            if errors:
                invalid_rows.append({
                    'row_num': row_num,
                    'student_id': student_id,
                    'name': name,
                    'errors': errors,
                })
                continue

            cleaned = {
                'row_num': row_num,
                'student_id': student_id,
                'name': name,
                'email': email,
                'phone': phone,
                'personal_email': personal_email,
                'department': dept,
                'academic_level': level,
                'section': section,
                'custom_courses': custom_courses,
            }

            if student_id in existing_students:
                cleaned['existing_student_id'] = existing_students[student_id].id
                existing_rows.append(cleaned)
            else:
                if email in existing_emails:
                    invalid_rows.append({
                        'row_num': row_num,
                        'student_id': student_id,
                        'name': name,
                        'errors': [f"Email '{email}' is already in use by another user account."],
                    })
                    continue
                valid_rows.append(cleaned)

        staging_token = uuid.uuid4().hex
        return {
            'staging_token': staging_token,
            'valid_rows': valid_rows,
            'existing_rows': existing_rows,
            'invalid_rows': invalid_rows,
            'selected_offerings': selected_offerings,
            'selected_offering_ids': selected_offering_ids,
        }

    @classmethod
    @transaction.atomic
    def execute_import(cls, staged_data, organization, admin_user):
        """
        Executes atomic database writes for staged data.
        Returns: (created_count, updated_count, enrollments_count)
        """
        policy = organization.get_provisioning_policy()
        valid_rows = staged_data.get('valid_rows', [])
        existing_rows = staged_data.get('existing_rows', [])
        selected_offering_ids = staged_data.get('selected_offering_ids', [])

        offerings = list(CourseOffering.objects.filter(
            id__in=selected_offering_ids,
            course__organization=organization
        ).prefetch_related('groups'))

        # Map groups by offering_id and normalized section digit
        offering_groups = defaultdict(dict)
        for off in offerings:
            for grp in off.groups.all():
                digits = re.findall(r'\d+', grp.name)
                if digits:
                    offering_groups[off.id][digits[0]] = grp
                offering_groups[off.id][grp.name.lower()] = grp

        created_students = 0
        updated_students = 0
        enrollments_created = 0

        # Helper to generate password
        def get_student_password(sid):
            if policy.password_strategy == 'RANDOM_TEMP':
                return secrets.token_urlsafe(12)
            try:
                return policy.password_pattern.format(student_id=sid, org_slug=organization.slug)
            except Exception:
                return f"{sid}#{organization.slug}!"

        # 1. Process New Students
        for row in valid_rows:
            first_name, last_name = cls.split_name(row['name'])
            password = get_student_password(row['student_id'])

            user = User.objects.create_user(
                email=row['email'],
                password=password,
                first_name=first_name,
                last_name=last_name,
                role=Role.STUDENT,
                organization=organization,
            )
            if policy.auto_activate_accounts:
                user.is_active = True
                user.save(update_fields=['is_active'])

            student = Student.objects.create(
                user=user,
                organization=organization,
                student_id=row['student_id'],
                department=row['department'],
                academic_level=row['academic_level'],
                phone=row['phone'],
                personal_email=row['personal_email'] or None,
            )
            created_students += 1

            # Enroll in selected offerings
            for off in offerings:
                group = None
                if row['section']:
                    group = offering_groups[off.id].get(row['section']) or offering_groups[off.id].get(f"section {row['section']}".lower())
                _, created = StudentEnrollment.objects.get_or_create(
                    student=student,
                    course_offering=off,
                    defaults={'group': group}
                )
                if created:
                    enrollments_created += 1

        # 2. Process Existing Students (Upsert / Re-enroll)
        for row in existing_rows:
            student = Student.objects.select_for_update().get(id=row['existing_student_id'], organization=organization)
            # Update metadata if provided
            if row['department']:
                student.department = row['department']
            if row['academic_level']:
                student.academic_level = row['academic_level']
            if row['phone']:
                student.phone = row['phone']
            if row['personal_email']:
                student.personal_email = row['personal_email']
            student.save()
            updated_students += 1

            # Append new enrollments
            for off in offerings:
                group = None
                if row['section']:
                    group = offering_groups[off.id].get(row['section']) or offering_groups[off.id].get(f"section {row['section']}".lower())
                _, created = StudentEnrollment.objects.get_or_create(
                    student=student,
                    course_offering=off,
                    defaults={'group': group}
                )
                if created:
                    enrollments_created += 1

        return created_students, updated_students, enrollments_created
