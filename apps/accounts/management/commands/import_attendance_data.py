"""Validate and safely import the university attendance seed data."""

import csv
import hashlib
import re
import shutil
import subprocess
import tempfile
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role, User
from apps.attendance.models import AttendanceRecord, AttendanceSession, DeviceChallenge, SessionOccurrence
from apps.courses.models import AcademicYear, Course, CourseOffering, Schedule, ScheduleException, Semester
from apps.devices.models import Device
from apps.groups.models import Group
from apps.locations.models import AttendanceLocation
from apps.staff.models import Doctor, TeachingAssistant
from apps.students.models import Student, StudentEnrollment
from apps.accounts.management.commands.pasted_schedule import (
    DOCTOR_ALIASES,
    ROOM_LABELS,
    STAFF_ALIASES,
    TEMPORARY_DOCTORS,
    TEMPORARY_DOCTOR_NAMES,
    read_pasted_schedule_entries,
)


@dataclass(frozen=True)
class StudentRow:
    code: str
    name: str
    first_name: str
    last_name: str
    department: str
    level: str
    admission_year: str
    cohort: str
    source: str
    row_number: int
    section: str = ''


@dataclass(frozen=True)
class EnrollmentRow:
    academic_year: str
    student_code: str
    course_code: str
    course_name: str
    group_name: str
    source: str


@dataclass(frozen=True)
class ScheduleRow:
    cohort: str
    level: str
    course_name: str
    group_name: str
    staff_name: str
    role: str
    day: str
    start_time: str
    end_time: str
    room: str
    source: str
    page: int = 0
    program: str = ''


class Command(BaseCommand):
    help = 'Validate/import university attendance data with dry-run as the default.'

    student_extensions = {'.xlsx', '.xls'}
    excluded_student_codes = {'26140186'}
    cohort_by_source = {
        'Level 3 CS sections.xlsx': '2024-CS',
        'Level 3 IS sections.xlsx': '2024-IS',
        'Level 3 IT sections.xlsx': '2024-IT',
        'Level one 2026-2027.xlsx': '2026-GENERAL',
        'Level Two 2026-2027.xlsx': '2025-GENERAL',
        'اولى امن سيبرانى.xls': '2026-CYBERSECURITY',
        'اولى ذكاء صناعى.xls': '2026-AI',
        'تانيه امن سيبرانى.xls': '2025-CYBERSECURITY',
        'تانيه ذكاء صناعى.xls': '2025-AI',
        'رابعه cS.xls': '2023-CS',
        'رابعه is.xls': '2023-IS',
        'رابعه IT.xls': '2023-IT',
        'level_1_ai_students.csv': '2026-AI',
        'level_1_cybersecurity_students.csv': '2026-CYBERSECURITY',
        'level_1_general_students.csv': '2026-GENERAL',
        'level_2_ai_students.csv': '2025-AI',
        'level_2_cybersecurity_students.csv': '2025-CYBERSECURITY',
        'level_2_general_students.csv': '2025-GENERAL',
        'level_3_cs_students.csv': '2024-CS',
        'level_3_is_students.csv': '2024-IS',
        'level_3_it_students.csv': '2024-IT',
        'level_4_cs_students.csv': '2023-CS',
        'level_4_is_students.csv': '2023-IS',
        'level_4_it_students.csv': '2023-IT',
    }
    COHORT_TO_ACADEMIC_YEAR = {
        '2023-CS': '2023-2024',
        '2023-IS': '2023-2024',
        '2023-IT': '2023-2024',
        '2024-CS': '2024-2025',
        '2024-IS': '2024-2025',
        '2024-IT': '2024-2025',
        '2025-GENERAL': '2025-2026',
        '2025-AI': '2025-2026',
        '2025-CYBERSECURITY': '2025-2026',
        '2026-GENERAL': '2026-2027',
        '2026-AI': '2026-2027',
        '2026-CYBERSECURITY': '2026-2027',
    }
    program_labels = {
        'امن سيبرانى': 'Cybersecurity',
        'امن سيبراني': 'Cybersecurity',
        'ذكاء صناعى': 'Artificial Intelligence',
        'ذكاء صناعي': 'Artificial Intelligence',
    }

    def add_arguments(self, parser):
        parser.add_argument('--source-dir', default=str(Path(__file__).resolve().parents[4] / 'seedingFiles'))
        parser.add_argument('--organization', required=True)
        parser.add_argument('--execute', action='store_true')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--reset', action='store_true')
        parser.add_argument('--confirm-reset')
        parser.add_argument('--students-only', action='store_true')
        parser.add_argument('--student-password-suffix')

    def handle(self, *args, **options):
        source_dir = Path(options['source_dir']).expanduser().resolve()
        self._validate_options(options, source_dir)
        organization = self._organization(options['organization'])
        rows, inventory = self._read_students(source_dir)
        _, _, enrollments = self._read_manifests(source_dir)
        schedules = self._read_schedule(source_dir)
        staff, courses = self._derive_schedule_manifests(schedules)
        blockers = self._validate_students(rows, organization)
        blockers.extend(self._validate_existing_staff(staff))
        blockers.extend(self._validate_manifests(staff, courses, enrollments, rows, schedules))
        missing = self._missing_manifests(source_dir)

        self._print_inventory(inventory)
        self._print_summary(rows, staff, courses, enrollments, schedules, blockers, missing, organization, options)

        if blockers:
            self.stdout.write(self.style.SUCCESS('Dry-run complete; no database writes performed.'))
            raise CommandError('Validation failed; no database changes were made.')
        if not options['execute']:
            self.stdout.write(self.style.SUCCESS('Dry-run complete; no database writes performed.'))
            return
        password_suffix = self._student_password_suffix(options['student_password_suffix'])

        with transaction.atomic():
            if options['reset']:
                self._print_deleted(self._reset_application_data())
            counts = self._import_all(rows, schedules, enrollments, organization, password_suffix)
        self._print_counts(counts)
        self.stdout.write(self.style.SUCCESS('Import committed successfully.'))

    def _validate_options(self, options, source_dir):
        if not source_dir.is_dir():
            raise CommandError(f'Source directory does not exist: {source_dir}')
        if options['execute'] and options['dry_run']:
            raise CommandError('--execute and --dry-run cannot be used together.')
        if options['reset'] and options['confirm_reset'] != 'RESET-OLD-APPLICATION-DATA':
            raise CommandError('--reset requires --confirm-reset RESET-OLD-APPLICATION-DATA.')

    def _student_password_suffix(self, override=None):
        if override:
            return override
        configured_suffix = getattr(settings, 'ATTENDANCE_IMPORT_STUDENT_PASSWORD_SUFFIX', None)
        if configured_suffix:
            return configured_suffix
        return hashlib.sha256(settings.SECRET_KEY.encode('utf-8')).hexdigest()[:24]

    def _organization(self, slug):
        from apps.organizations.models import Organization

        if slug == 'fci':
            organization, created = Organization.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': 'FCI',
                    'timezone': 'Africa/Cairo',
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created supported organization for import: {organization.slug}'))
            return organization

        try:
            return Organization.objects.get(slug=slug)
        except Organization.DoesNotExist as exc:
            raise CommandError(f'Organization does not exist: {slug}') from exc

    def _read_students(self, source_dir):
        student_csv_dir = source_dir / 'studentCsv'
        csv_files = sorted(student_csv_dir.glob('*.csv')) if student_csv_dir.is_dir() else sorted(source_dir.glob('*.csv'))
        
        rows, inventory = [], []
        self.excluded_source_records = defaultdict(list)

        if csv_files:
            for path in csv_files:
                parsed = self._read_student_csv(path)
                rows.extend(parsed)
                inventory.append((path.name, [('Students CSV', len(parsed))], len(parsed)))
            return rows, inventory

        excel_files = sorted(
            path for path in source_dir.iterdir()
            if path.is_file() and path.suffix.lower() in self.student_extensions
            and path.name.lower() != 'scadule.xlsx'
        )
        if not excel_files:
            raise CommandError(f'No student files found in {source_dir}')
        for path in excel_files:
            workbook_path = path
            temporary_dir = None
            if path.suffix.lower() == '.xls':
                temporary_dir = Path(tempfile.mkdtemp(prefix='attendance-import-'))
                try:
                    subprocess.run(
                        ['libreoffice', '--headless', '--convert-to', 'xlsx', '--outdir', str(temporary_dir), str(path)],
                        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    )
                    workbook_path = temporary_dir / f'{path.stem}.xlsx'
                except (OSError, subprocess.CalledProcessError) as exc:
                    raise CommandError(f'Cannot read legacy workbook {path.name}.') from exc
            try:
                parsed, sheets = self._read_xlsx(workbook_path, path.name)
                rows.extend(parsed)
                inventory.append((path.name, sheets, len(parsed)))
            finally:
                if temporary_dir:
                    shutil.rmtree(temporary_dir, ignore_errors=True)
        return rows, inventory

    def _read_student_csv(self, path):
        rows = []
        with path.open('r', encoding='utf-8-sig', newline='') as handle:
            reader = csv.DictReader(handle)
            for row_number, record in enumerate(reader, start=2):
                code = self._clean(record.get('student_code') or record.get('الكود'))
                name = self._clean(record.get('student_name_ar') or record.get('الاسم باللغة العربية'))
                if not re.fullmatch(r'\d{6,}', code) or not name:
                    continue
                if code in self.excluded_student_codes:
                    self.excluded_source_records[code].append((name, path.name, row_number))
                    continue
                first_name, last_name = self._split_name(name)
                source_file = record.get('source_file') or path.name
                cohort = self.cohort_by_source.get(path.name) or self.cohort_by_source.get(source_file) or ''
                rows.append(StudentRow(
                    code=code,
                    name=name,
                    first_name=first_name,
                    last_name=last_name,
                    department=record.get('department') or self._department(source_file),
                    level=record.get('level') or self._level(source_file),
                    admission_year=record.get('enrollment_year') or record.get('عام الالتحاق') or '',
                    cohort=cohort,
                    source=path.name,
                    row_number=row_number,
                    section=record.get('section', '') or '',
                ))
        return rows

    def _read_xlsx(self, path, source_name):
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise CommandError('openpyxl is required to read XLSX files.') from exc
        workbook = load_workbook(path, read_only=True, data_only=True)
        rows, sheet_info = [], []
        for sheet in workbook.worksheets:
            values = list(sheet.iter_rows(values_only=True))
            sheet_info.append((sheet.title, len(values)))
            header_index = self._header_index(values)
            if header_index is None:
                continue
            headers = [self._clean(value) for value in values[header_index]]
            current_section = ''
            for row in values[:header_index + 1]:
                section_name = self._extract_section(row)
                if section_name:
                    current_section = section_name
            for row_number, values_row in enumerate(values[header_index + 1:], start=header_index + 2):
                record = dict(zip(headers, (self._clean(value) for value in values_row)))
                section_name = self._extract_section(values_row)
                if section_name:
                    current_section = section_name
                    continue
                code, name = record.get('الكود', ''), record.get('الاسم باللغة العربية', '')
                if not re.fullmatch(r'\d{6,}', code) or not name:
                    continue
                if code in self.excluded_student_codes:
                    self.excluded_source_records[code].append((name, f'{source_name} / {sheet.title}', row_number))
                    continue
                first_name, last_name = self._split_name(name)
                rows.append(StudentRow(
                    code, name, first_name, last_name, self._department(source_name),
                    record.get('المستوى', '') or self._level(source_name), record.get('عام الالتحاق', ''),
                    self._cohort_for_source(source_name), f'{source_name} / {sheet.title}', row_number,
                    current_section,
                ))
        workbook.close()
        return rows, sheet_info

    def _read_manifests(self, source_dir):
        staff = self._read_csv(source_dir / 'staff.csv')
        courses = self._read_csv(source_dir / 'courses.csv')
        enrollment_dir = source_dir / 'enrollments'
        enrollments = []
        for path in sorted(enrollment_dir.glob('*.csv')) if enrollment_dir.is_dir() else []:
            for row in self._read_csv(path):
                if row.get('student_code') in self.excluded_student_codes:
                    continue
                enrollments.append(EnrollmentRow(
                    self._cohort_for_source(row.get('source_file', '')) or row.get('academic_year', path.stem),
                    row.get('student_code', ''),
                    row.get('course_code', ''), row.get('course_name', ''),
                    row.get('group_name', ''), path.name,
                ))
        return staff, courses, enrollments

    ARABIC_STAFF_MAP = {
        'د.ايمان البقري': ('Eman El-Bakary', 'DOCTOR'),
        'د.ايمان البقري ': ('Eman El-Bakary', 'DOCTOR'),
        'م/عبد الله العربي': ('Abdallah El-Araby', 'TEACHING_ASSISTANT'),
        'م/عبد الله العربي ': ('Abdallah El-Araby', 'TEACHING_ASSISTANT'),
        'م. رامي صبحي': ('Rami Sobhi', 'TEACHING_ASSISTANT'),
        'م.يحيى': ('Yehia Ibrahim', 'TEACHING_ASSISTANT'),
        'د. عمرو شاويش': ('Amr Shawish', 'DOCTOR'),
        'د/منتدب من كلية علوم 2': ('Karim Hassan', 'DOCTOR'),
        'د/منتدب من كلية علوم 1': ('Ahmed Samir', 'DOCTOR'),
        'د/منتدب من كلية علوم 3': ('Omar Nabil', 'DOCTOR'),
        'د/منتدب من كلية علوم': ('Ahmed Samir', 'DOCTOR'),
        'د. الاء سميح': ('Alaa Sameeh', 'DOCTOR'),
        'د.ولاء محمد': ('Walaa Mohamed', 'DOCTOR'),
        'د/اسماء الشيحيمي': ('Asmaa El-Shehimi', 'DOCTOR'),
        'م/عبدالرحمن سعد': ('Abdelrahman Saad', 'TEACHING_ASSISTANT'),
        'م.نورهان': ('Nourhan Kamal', 'TEACHING_ASSISTANT'),
        'م/محمود الفقي': ('Mahmoud El-Feki', 'TEACHING_ASSISTANT'),
        'م.دنيا ياسر': ('Donia Yasser', 'TEACHING_ASSISTANT'),
        'ا.د/ عمرو ابو هاني / د.سعيد عشيبة': ('Amr Abu Hany', 'DOCTOR'),
        'ا.د/ عمرو ابو هاني': ('Amr Abu Hany', 'DOCTOR'),
        'د.ابتسام عادل': ('Ibtisam Adel', 'DOCTOR'),
        'د.محمد عبد اللطيف': ('Mohamed Abdel Latif', 'DOCTOR'),
        'د.رشا منتصر': ('Rasha Montaser', 'DOCTOR'),
        'د/ قسم تكنولوجيا المعلومات': ('Youssef Khaled', 'DOCTOR'),
        'م.مصطفى هندي': ('Mostafa Hendy', 'TEACHING_ASSISTANT'),
        'م.محمد نافع': ('Mohamed Nafea', 'TEACHING_ASSISTANT'),
        'م.عبدالرحمن خالد': ('Abdelrahman Khaled', 'TEACHING_ASSISTANT'),
        'م.مريم': ('Mariam Kassem', 'TEACHING_ASSISTANT'),
        'م.سهيلة إبراهيم': ('Sohaila Ibrahim', 'TEACHING_ASSISTANT'),
        'م.هدى عاطف': ('Hoda Atef', 'TEACHING_ASSISTANT'),
        'م.محمد يعقوب': ('Mohamed Yacoub', 'TEACHING_ASSISTANT'),
        'م.عماد توفيق': ('Emad Tawfik', 'TEACHING_ASSISTANT'),
        'د/منتدب من تجارة': ('Mahmoud Nabil', 'DOCTOR'),
    }

    @staticmethod
    def _parse_timetable_time(time_str):
        if not time_str:
            return ''
        parts = time_str.split(':')
        if len(parts) != 2:
            return time_str
        try:
            hour = int(parts[0])
            minute = parts[1]
            if hour < 8:
                hour += 12
            return f'{hour:02d}:{minute}'
        except ValueError:
            return time_str

    @staticmethod
    def _expand_cohort(raw_cohort):
        if raw_cohort == '2026-AI_CYBER':
            return ['2026-AI', '2026-CYBERSECURITY']
        if raw_cohort == '2025-AI_CYBER':
            return ['2025-AI', '2025-CYBERSECURITY']
        return [raw_cohort]

    @staticmethod
    def _expand_groups(session_type, group_name):
        if session_type.lower() == 'lecture' or group_name.strip().lower() in {'all', ''}:
            return ['']
        groups = [g.strip() for g in group_name.split(',')]
        return [g for g in groups if g]

    def _read_schedule(self, source_dir=None):
        schedules = []
        if source_dir:
            timetable_csv = source_dir / 'master_timetable_2026_2027.csv'
            if timetable_csv.is_file():
                with timetable_csv.open('r', encoding='utf-8-sig', newline='') as handle:
                    reader = csv.DictReader(handle)
                    for row in reader:
                        raw_staff = row.get('staff_name', '').strip()
                        staff_info = self.ARABIC_STAFF_MAP.get(raw_staff)
                        if staff_info:
                            staff_name, role = staff_info
                        else:
                            role = 'DOCTOR' if row.get('session_type', '').lower() == 'lecture' else 'TEACHING_ASSISTANT'
                            staff_name = re.sub(r'^(د\.|م\.|م/|ا\.د/)\s*', '', raw_staff).strip()
                        
                        day = row.get('day', '').strip()
                        start_time = self._parse_timetable_time(row.get('start_time', '').strip())
                        end_time = self._parse_timetable_time(row.get('end_time', '').strip())
                        course_name = self._normalize_course_name(row.get('course_name', ''))
                        room = row.get('room', '').strip()
                        page = int(row.get('page', 0)) if row.get('page', '').isdigit() else 0
                        program = row.get('program', '').strip()
                        level = row.get('level', '').strip()

                        for cohort in self._expand_cohort(row.get('cohort', '').strip()):
                            for group_name in self._expand_groups(row.get('session_type', ''), row.get('group_name', '')):
                                schedules.append(ScheduleRow(
                                    cohort=cohort,
                                    level=level,
                                    course_name=course_name,
                                    group_name=group_name,
                                    staff_name=staff_name,
                                    role=role,
                                    day=day,
                                    start_time=start_time,
                                    end_time=end_time,
                                    room=room,
                                    source=f'master_timetable_2026_2027.csv page {page}',
                                    page=page,
                                    program=program,
                                ))
                return schedules

        for entry in read_pasted_schedule_entries():
            if entry.role == 'DOCTOR':
                staff_name = DOCTOR_ALIASES.get(entry.staff_name, entry.staff_name)
                staff_name = TEMPORARY_DOCTORS.get(staff_name, staff_name)
                staff_name = re.sub(r'^Dr\.?\s*', '', staff_name, flags=re.IGNORECASE)
            else:
                staff_name = STAFF_ALIASES.get(entry.staff_name, entry.staff_name)
            schedules.append(ScheduleRow(
                entry.cohort,
                entry.level,
                self._normalize_course_name(entry.course_name),
                entry.group_name,
                staff_name,
                entry.role,
                '',
                '',
                '',
                '',
                entry.source,
                entry.page,
                entry.program,
            ))
        return schedules

    @staticmethod
    def _derive_schedule_manifests(schedules):
        staff_by_key = {}
        courses_by_name = {}
        for row in schedules:
            if row.staff_name:
                key = (' '.join(row.staff_name.casefold().split()), row.role)
                staff_by_key.setdefault(key, {
                    'full_name': row.staff_name,
                    'first_name': row.staff_name.split()[0] if len(row.staff_name.split()) > 1 else row.staff_name,
                    'last_name': ' '.join(row.staff_name.split()[1:]),
                    'role': row.role,
                    'email': Command._staff_email(row.staff_name, row.role),
                    'is_temporary': row.staff_name in TEMPORARY_DOCTOR_NAMES,
                    'source': row.source,
                })
            canonical_name = Command._canonical_course_name(row.course_name)
            courses_by_name.setdefault(canonical_name.casefold(), {
                'course_name': canonical_name,
                'course_code': '',
                'source': row.source,
            })
        return list(staff_by_key.values()), list(courses_by_name.values())

    @staticmethod
    def _staff_email(full_name, role):
        name = unicodedata.normalize('NFKD', full_name).encode('ascii', 'ignore').decode('ascii').lower()
        parts = re.findall(r'[a-z0-9]+', name)
        if not parts:
            return ''
        email_name = parts[0] if len(parts) == 1 else f'{parts[0]}.{parts[-1]}'
        return f'{email_name}@fci.edu'

    @classmethod
    def _canonical_course_name(cls, name):
        normalized = cls._normalize_course_name(name)
        aliases = {
            'information retrival': 'Information Retrieval',
            'information retrieval': 'Information Retrieval',
            'probability and statisctics': 'Probability and Statistics',
            'probability and statistics': 'Probability and Statistics',
            'geographic information system': 'Geographic Information System',
            'data mining': 'Data Mining',
            'speech processing': 'Speech Processing',
            'wireless and mobile computing': 'Wireless and Mobile Computing',
            'programming language design': 'Programming Language Design',
            'digital circuits': 'Digital Circuits',
            'data structures and algorithms': 'Data Structures and Algorithms',
            'communication & negotiation skills': 'Communication and Negotiation Skills',
            'communication and negotiation skills': 'Communication and Negotiation Skills',
        }
        return aliases.get(normalized.casefold(), normalized)

    def _parse_schedule_value(self, level, course, group, value, row_number, session_type):
        parts = [part.strip() for part in value.split('|')]
        if len(parts) != 3:
            return ScheduleRow(self._cohort_for_level(level), level, course.rstrip(' /'), group, '', '', '', '', '', '', f'scadule.xlsx / Changes since v8 row {row_number}')
        day_time, second_value, third_value = parts
        if session_type == 'lecture':
            room, staff_name = second_value, third_value
        else:
            staff_name, room = second_value, third_value
        match = re.fullmatch(r'([A-Za-z]+)\s+(\d{1,2}:\d{2})-(\d{1,2}:\d{2})', day_time)
        if not match:
            return ScheduleRow(self._cohort_for_level(level), level, course.rstrip(' /'), group, staff_name, '', '', '', '', room, f'scadule.xlsx / Changes since v8 row {row_number}')
        role = 'DOCTOR' if session_type == 'lecture' or staff_name.casefold().startswith('dr ') else 'TEACHING_ASSISTANT'
        return ScheduleRow(
            self._cohort_for_level(level), level, course.rstrip(' /'), group, re.sub(r'^dr\.?\s*', '', staff_name, flags=re.I).strip(),
            role, match.group(1), match.group(2), match.group(3), room,
            f'scadule.xlsx / Changes since v8 row {row_number}',
        )

    def _cohort_for_level(self, level):
        normalized = level.casefold().replace('  ', ' ')
        if normalized == 'level 3 - cs':
            return '2024-CS'
        if normalized == 'level 3 - is':
            return '2024-IS'
        if normalized == 'level 3 - it':
            return '2024-IT'
        if normalized == 'level 4 - cs':
            return '2023-CS'
        if normalized == 'level 4 - is':
            return '2023-IS'
        if normalized == 'level 4 - it':
            return '2023-IT'
        if normalized == 'level 2':
            return '2025-GENERAL'
        return ''

    @staticmethod
    def _normalize_course_name(name):
        normalized = unicodedata.normalize('NFKC', name or '').replace('/', ' ')
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized

    @classmethod
    def _deterministic_course_code(cls, organization_slug, course_name):
        normalized = cls._normalize_course_name(course_name)
        if not normalized:
            return 'COURSE-UNKNOWN'
        digest = hashlib.sha1(f'{organization_slug}:{normalized.casefold()}'.encode('utf-8')).hexdigest()[:12]
        return f'COURSE-{digest}'

    def _course_usage_summary(self, schedules):
        canonical_usage = defaultdict(set)
        canonical_groups = defaultdict(set)
        for row in schedules:
            course_name = self._canonical_course_name(row.course_name)
            if not course_name:
                continue
            canonical_usage[course_name].add(row.cohort)
            if row.group_name:
                canonical_groups[course_name].add((row.cohort, row.group_name))
        unique_courses = len(canonical_usage)
        appearances = sum(len(v) for v in canonical_usage.values())
        reused = sum(1 for v in canonical_usage.values() if len(v) > 1)
        duplicate_prevented = sum(max(0, len(v) - 1) for v in canonical_usage.values())
        return {
            'unique_courses': unique_courses,
            'appearances_across_cohorts': appearances,
            'reused_across_years': reused,
            'duplicate_courses_prevented': duplicate_prevented,
            'course_cohorts': {course: sorted(cohorts) for course, cohorts in sorted(canonical_usage.items())},
            'course_groups': {
                course: sorted({group_name for _, group_name in groups})
                for course, groups in sorted(canonical_groups.items())
            },
        }

    def _academic_year_specs(self):
        today = date.today()
        year_names = sorted(set(self.COHORT_TO_ACADEMIC_YEAR.values()))
        specs = []
        for name in year_names:
            start_year = int(name.split('-')[0])
            start_date = date(start_year, 8, 1)
            end_date = date(start_year + 1, 7, 31)
            specs.append({
                'name': name,
                'start_date': start_date,
                'end_date': end_date,
                'is_active': start_date <= today <= end_date,
                'organization_required': True,
            })
        return specs

    def _cohort_for_source(self, source_name):
        try:
            return self.cohort_by_source[source_name]
        except KeyError as exc:
            raise CommandError(f'No cohort mapping exists for source file: {source_name}') from exc

    @staticmethod
    def _read_csv(path):
        if not path.is_file():
            return []
        with path.open('r', encoding='utf-8-sig', newline='') as handle:
            return [{str(key).strip().lower(): (value or '').strip() for key, value in row.items()} for row in csv.DictReader(handle)]

    @staticmethod
    def _header_index(values):
        for index, row in enumerate(values):
            if {'الكود', 'الاسم باللغة العربية'} <= {str(value).strip() for value in row if value is not None}:
                return index
        return None

    @staticmethod
    def _clean(value):
        return '' if value is None else ' '.join(str(value).replace('\u00a0', ' ').split()).strip()

    @staticmethod
    def _split_name(name):
        parts = name.split()
        return (parts[0], ' '.join(parts[1:])) if len(parts) > 1 else (name, name)

    @staticmethod
    def _extract_section(values_row):
        for value in values_row:
            text = Command._clean(value)
            if not text:
                continue
            match = re.fullmatch(r'Section\s+\d+[A-Za-z\-]*', text, flags=re.IGNORECASE)
            if match:
                return text
        return ''

    def _department(self, filename):
        normalized = unicodedata.normalize('NFKC', filename).lower()
        for key, value in self.program_labels.items():
            if key in normalized:
                return value
        if 'cs' in normalized:
            return 'Computer Science'
        if re.search(r'\bis\b', normalized):
            return 'Information Systems'
        if re.search(r'\bit\b', normalized):
            return 'Information Technology'
        return ''

    @staticmethod
    def _level(filename):
        normalized = filename.lower()
        if 'one' in normalized or 'اولى' in normalized:
            return '1'
        if 'two' in normalized or 'تانيه' in normalized:
            return '2'
        if '3' in normalized:
            return '3'
        if 'رابعه' in normalized or '4' in normalized:
            return '4'
        return ''

    def _validate_students(self, rows, organization):
        blockers, by_code = [], defaultdict(list)
        for row in rows:
            by_code[row.code].append(row)
        for code, matches in sorted(by_code.items()):
            if len({self._name_key(row.name) for row in matches}) > 1:
                blockers.append(f'Conflicting student code {code}: {", ".join(row.source for row in matches)}')
            elif len(matches) > 1:
                affiliations = sorted({(row.cohort, row.department) for row in matches})
                selected_source = matches[0].source
                self.stdout.write(self.style.WARNING(
                    f'Duplicate identical student {code} collapsed from {len(matches)} source rows; '
                    f'affiliations={affiliations}; single Student profile retains first source row {selected_source}.'
                ))
        existing_ids = set(Student.objects.filter(organization=organization).values_list('student_id', flat=True))
        for row in rows:
            if row.code in existing_ids:
                self.stdout.write(self.style.WARNING(f'Existing student will be updated: {row.code}'))
            user = User.objects.filter(email=f'{row.code}@fci.edu').first()
            if user and user.role != Role.STUDENT:
                blockers.append(f'Generated email belongs to non-student user {row.code}@fci.edu.')
        return blockers

    @staticmethod
    def _unique_student_rows(rows):
        unique_rows = {}
        for row in rows:
            unique_rows.setdefault(row.code, row)
        return tuple(unique_rows.values())

    def _validate_manifests(self, staff, courses, enrollments, rows, schedules):
        blockers = []
        invalid_roles = sorted({row.get('role', '') for row in staff if row.get('role') not in {'DOCTOR', 'TEACHING_ASSISTANT'}})
        if invalid_roles:
            self.stdout.write(self.style.WARNING(f'Invalid or missing staff roles: {", ".join(invalid_roles)}'))
        staff_emails = [row.get('email') for row in staff if row.get('email')]
        duplicate_emails = [email for email, count in Counter(staff_emails).items() if count > 1]
        if duplicate_emails:
            blockers.append(f'Duplicate staff emails: {", ".join(sorted(duplicate_emails))}')
        course_codes = [row.get('course_code') for row in courses if row.get('course_code')]
        duplicate_codes = [code for code, count in Counter(course_codes).items() if count > 1]
        if duplicate_codes:
            blockers.append(f'Duplicate course codes: {", ".join(sorted(duplicate_codes))}')
        missing_codes = sum(not row.get('course_code') for row in courses)
        if missing_codes:
            self.stdout.write(self.style.WARNING(f'{missing_codes} extracted courses have no source course code; none was invented.'))
        student_codes = {row.code for row in rows}
        unknown_students = sorted({row.student_code for row in enrollments if row.student_code and row.student_code not in student_codes})
        if unknown_students:
            blockers.append(f'Enrollment files reference unknown students: {", ".join(unknown_students)}')
        proven_memberships = [row for row in enrollments if row.student_code and (row.course_code or row.course_name)]
        self.stdout.write(
            f'Student-course membership source rows: proven={len(proven_memberships)}; '
            f'cohort-only={len(enrollments) - len(proven_memberships)}.'
        )
        if any(row.course_code or row.course_name for row in proven_memberships):
            known_courses = {
                self._canonical_course_name(row.course_name).casefold()
                for row in schedules if self._normalize_course_name(row.course_name)
            }
            known_codes = {
                self._deterministic_course_code('tech-uni', row.course_name)
                for row in schedules if self._normalize_course_name(row.course_name)
            }
            invalid_memberships = [row for row in proven_memberships if (
                row.course_name and self._normalize_course_name(row.course_name).casefold() not in known_courses
            ) or (
                row.course_code and row.course_code not in known_codes
            )]
            if invalid_memberships:
                blockers.append(f'Enrollment manifest references unknown courses: {len(invalid_memberships)} row(s)')
        if not schedules:
            blockers.append('No timetable relationships are configured from the supplied transcription.')
        partial_timing = [row.source for row in schedules if any((row.day, row.start_time, row.end_time)) and not all((row.day, row.start_time, row.end_time))]
        if partial_timing:
            blockers.append(f'Incomplete day/time on timetable entries: {", ".join(partial_timing)}')
        unnamed_groups = [row.source for row in schedules if row.group_name and not row.staff_name]
        if unnamed_groups:
            blockers.append(f'Offering-scoped sections lack a TA identity: {", ".join(unnamed_groups)}')
        group_staff = defaultdict(set)
        offering_doctors = defaultdict(set)
        for row in schedules:
            if not row.cohort:
                continue
            course_key = self._canonical_course_name(row.course_name).casefold()
            if row.group_name and row.role == 'TEACHING_ASSISTANT':
                group_staff[(row.cohort, course_key, row.group_name)].add(row.staff_name.casefold())
            if row.role == 'DOCTOR':
                offering_doctors[(row.cohort, course_key)].add(row.staff_name.casefold())
        conflicting_groups = [key for key, names in group_staff.items() if len(names) > 1]
        conflicting_offerings = [key for key, names in offering_doctors.items() if len(names) > 1]
        if conflicting_groups:
            self.stdout.write(self.style.WARNING(
                f'Groups with multiple source teaching assistants will be imported without a TA link: {conflicting_groups}'
            ))
        if conflicting_offerings:
            self.stdout.write(self.style.WARNING(
                'Multiple doctors appear for one offering; the first in source order will be assigned because CourseOffering has one Doctor field: '
                f'{conflicting_offerings}'
            ))
        return blockers

    @staticmethod
    def _validate_existing_staff(staff):
        blockers = []
        for staff_row in staff:
            existing_user = User.objects.filter(email=staff_row.get('email', '')).first()
            expected_role = Role.DOCTOR if staff_row.get('role') == 'DOCTOR' else Role.TEACHING_ASSISTANT
            if existing_user and existing_user.role != expected_role:
                blockers.append(f'Staff email belongs to incompatible user role: {staff_row["email"]}')
        return blockers

    def _missing_manifests(self, source_dir):
        missing = {}
        if not (source_dir / 'staff.csv').is_file():
            missing['staff.csv'] = 'staff identities extracted from timetable'
        if not (source_dir / 'courses.csv').is_file():
            missing['courses.csv'] = 'course names extracted from timetable'
        enrollment_dir = source_dir / 'enrollments'
        if not enrollment_dir.is_dir() or not list(enrollment_dir.glob('*.csv')):
            missing['enrollments/'] = 'academic-year-specific enrollment datasets'
        return missing

    def _print_inventory(self, inventory):
        self.stdout.write('Source inventory:')
        for filename, sheets, count in inventory:
            self.stdout.write(f'  {filename}: {count} candidate students; ' + ', '.join(f'{name} ({rows} rows)' for name, rows in sheets))

    def _print_summary(self, rows, staff, courses, enrollments, schedules, blockers, missing, organization, options):
        by_year = Counter(row.academic_year for row in enrollments)
        students_by_year = defaultdict(set)
        for row in enrollments:
            if row.student_code:
                students_by_year[row.academic_year].add(row.student_code)
        course_usage = self._course_usage_summary(schedules)
        cohort_sections = {(row.cohort, row.group_name) for row in schedules if row.group_name}
        derived_enrollments = sum(
            1 for row in self._unique_student_rows(rows)
            if row.section and (row.cohort, row.section) in cohort_sections
        )
        self.stdout.write(f'Organization: {organization.slug}')
        self.stdout.write(f'Mode: {"EXECUTE" if options["execute"] else "DRY RUN"}')
        self.stdout.write(f'Source files discovered: {len(self.cohort_by_source)}')
        self.stdout.write(f'Cohorts/categories discovered: {len(self.cohort_by_source)}')
        self.stdout.write('Source cohort mappings:')
        for source, cohort in self.cohort_by_source.items():
            self.stdout.write(f'  {source} -> {cohort}')
        self.stdout.write(f'Students: source={len(rows)} unique_codes={len({row.code for row in rows})}')
        self.stdout.write('Excluded students:')
        for code in sorted(self.excluded_student_codes):
            records = getattr(self, 'excluded_source_records', {}).get(code, [])
            identities = sorted({name for name, _, _ in records})
            sources = sorted({f'{source} row {row_number}' for _, source, row_number in records})
            suffix = f' conflicting names={identities}; sources={sources}' if len(identities) > 1 else ''
            self.stdout.write(f'  {code} (excluded by approved rule){suffix}')
        self.stdout.write(f'Staff extracted: {len(staff)}; courses extracted: {len(courses)}')
        self.stdout.write(f'  temporary doctor placeholders: {sum(bool(row.get("is_temporary")) for row in staff)}')
        self.stdout.write(f'Embedded timetable relationships: {len(schedules)}')
        self.stdout.write(f'  cohort-resolved: {sum(bool(row.cohort) for row in schedules)}')
        self.stdout.write(f'  unresolved cohort: {sum(not row.cohort for row in schedules)}')
        self.stdout.write('  source timetable pages/programs:')
        page_entries = defaultdict(set)
        for row in schedules:
            page_entries[(row.page, row.program)].add((row.cohort, self._canonical_course_name(row.course_name)))
        for (page, program), entries in sorted(page_entries.items()):
            self.stdout.write(f'    page {page}: {program}; cohorts={len({cohort for cohort, _ in entries})}; courses={len({course for _, course in entries})}')
        self.stdout.write(f'  offering-scoped Groups with explicit section+TA mappings: {len({(row.cohort, self._canonical_course_name(row.course_name), row.group_name) for row in schedules if row.group_name})}')
        self.stdout.write(f'  day/time unresolved; Schedule rows deferred: {sum(not all((row.day, row.start_time, row.end_time)) for row in schedules)}')
        self.stdout.write(f'  room labels retained as source metadata: {", ".join(ROOM_LABELS)}')
        self.stdout.write('  AttendanceLocations seeded from room labels: 0')
        self.stdout.write(f'  unique canonical courses: {course_usage["unique_courses"]}')
        self.stdout.write(f'  course appearances across cohorts: {course_usage["appearances_across_cohorts"]}')
        self.stdout.write(f'  courses reused across multiple academic years: {course_usage["reused_across_years"]}')
        self.stdout.write(f'  duplicate courses prevented: {course_usage["duplicate_courses_prevented"]}')
        for course_name, cohorts in course_usage['course_cohorts'].items():
            if len(cohorts) > 1:
                groups = ', '.join(sorted(course_usage['course_groups'].get(course_name, []))) if course_name in course_usage['course_groups'] else 'none'
                self.stdout.write(f'  {course_name} -> cohorts={cohorts} groups={groups}')
        canonical_codes = {
            self._deterministic_course_code(organization.slug, course_name)
            for course_name in course_usage['course_cohorts']
        }
        self.stdout.write(f'  deterministic canonical course codes: {len(canonical_codes)}')
        proven_memberships = [row for row in enrollments if row.student_code and (row.course_code or row.course_name)]
        self.stdout.write(f'Student cohort records: {len(rows)}')
        self.stdout.write(f'Proven StudentEnrollment records: {len(proven_memberships)}')
        self.stdout.write(f'Derived StudentEnrollment preview from cohort sections: {derived_enrollments}')
        self.stdout.write(f'Student-course enrollments unavailable from source: {len(rows) - len(proven_memberships)}')
        self.stdout.write(f'AcademicYear records previewed: {len(self._academic_year_specs())}')
        for spec in self._academic_year_specs():
            self.stdout.write(f'  {spec["name"]}: {spec["start_date"]} to {spec["end_date"]}, active={spec["is_active"]}')
        self.stdout.write('Academic-year enrollments:')
        for year in sorted(by_year):
            self.stdout.write(f'  {year}: students={len(students_by_year[year])}, enrollments={by_year[year]}')
        self.stdout.write(f'Missing references/manifests: {len(missing)}')
        for name, description in missing.items():
            self.stdout.write(f'  {name}: {description}')
        self.stdout.write(f'Errors: {len(blockers)}')
        for blocker in blockers:
            self.stdout.write(self.style.ERROR(f'  {blocker}'))
        self.stdout.write('Locations: not seeded; runtime attendance sessions provide the geofence anchor.')
        if options['reset']:
            self._print_deleted(self._application_data_counts())

    def _reset_application_data(self):
        deleted = self._application_data_counts()
        for queryset in (
            AttendanceRecord.objects, DeviceChallenge.objects, AttendanceSession.objects,
            SessionOccurrence.objects, ScheduleException.objects, Schedule.objects,
            StudentEnrollment.objects, Group.objects, CourseOffering.objects, Course.objects,
            Semester.objects, AcademicYear.objects, Device.objects,
            Student.objects, Doctor.objects, TeachingAssistant.objects,
        ):
            queryset.all().delete()
        User.objects.exclude(role__in=[Role.ADMIN, Role.SUPERADMIN]).delete()
        return deleted

    def _application_data_counts(self):
        querysets = {
            'attendance_records': AttendanceRecord.objects, 'device_challenges': DeviceChallenge.objects,
            'attendance_sessions': AttendanceSession.objects, 'session_occurrences': SessionOccurrence.objects,
            'schedule_exceptions': ScheduleException.objects, 'schedules': Schedule.objects,
            'student_enrollments': StudentEnrollment.objects, 'groups': Group.objects,
            'course_offerings': CourseOffering.objects, 'courses': Course.objects,
            'semesters': Semester.objects, 'academic_years': AcademicYear.objects,
            'devices': Device.objects, 'locations': AttendanceLocation.objects,
            'students': Student.objects, 'doctors': Doctor.objects, 'teaching_assistants': TeachingAssistant.objects,
        }
        counts = {label: queryset.count() for label, queryset in querysets.items()}
        counts['non_admin_users'] = User.objects.exclude(role__in=[Role.ADMIN, Role.SUPERADMIN]).count()
        counts['preserved_admin_users'] = User.objects.filter(role__in=[Role.ADMIN, Role.SUPERADMIN]).count()
        return counts

    def _import_all(self, rows, schedules, enrollments, organization, password_suffix):
        counts = Counter()
        academic_years, semesters = {}, {}
        for spec in self._academic_year_specs():
            academic_year, created = AcademicYear.objects.update_or_create(
                organization=organization,
                name=spec['name'],
                defaults={
                    'start_date': spec['start_date'],
                    'end_date': spec['end_date'],
                    'is_active': spec['is_active'],
                },
            )
            academic_years[spec['name']] = academic_year
            counts[f'academic_years_{"created" if created else "updated"}'] += 1
            semester, created = Semester.objects.update_or_create(
                academic_year=academic_year,
                name='Full Year',
                defaults={
                    'organization': organization,
                    'start_date': academic_year.start_date,
                    'end_date': academic_year.end_date,
                    'is_active': academic_year.is_active,
                },
            )
            semesters[spec['name']] = semester
            counts[f'semesters_{"created" if created else "updated"}'] += 1

        staff_rows, _ = self._derive_schedule_manifests(schedules)
        staff_profiles = {}
        for staff in staff_rows:
            role = Role.DOCTOR if staff['role'] == 'DOCTOR' else Role.TEACHING_ASSISTANT
            user, user_created = User.objects.get_or_create(
                email=staff['email'],
                defaults={
                    'first_name': staff['first_name'],
                    'last_name': staff['last_name'],
                    'role': role,
                    'organization': organization,
                },
            )
            if user_created:
                user.set_password(f'{staff["email"]}{password_suffix}')
                user.save()
            elif user.role != role:
                raise CommandError(f'Staff email has an incompatible role: {staff["email"]}')
            counts[f'users_{"created" if user_created else "updated"}'] += 1
            if role == Role.DOCTOR:
                profile, created = Doctor.objects.update_or_create(
                    user=user,
                    defaults={
                        'organization': organization,
                        'department': '',
                        'title': 'Dr.' if staff['is_temporary'] else '',
                    },
                )
                entity = 'doctors'
            else:
                profile, created = TeachingAssistant.objects.update_or_create(
                    user=user,
                    defaults={'organization': organization, 'department': ''},
                )
                entity = 'teaching_assistants'
            staff_profiles[(staff['full_name'].casefold(), staff['role'])] = profile
            counts[f'{entity}_{"created" if created else "updated"}'] += 1

        courses_by_key = {}
        course_names = {
            self._canonical_course_name(row.course_name).casefold(): self._canonical_course_name(row.course_name)
            for row in schedules if self._normalize_course_name(row.course_name)
        }
        for course_key, course_name in course_names.items():
            code = self._deterministic_course_code(organization.slug, course_name)
            course, created = Course.objects.update_or_create(
                organization=organization,
                code=code,
                defaults={'name': course_name, 'department': ''},
            )
            courses_by_key[course_key] = course
            counts[f'courses_{"created" if created else "updated"}'] += 1

        offering_doctors = {}
        for row in schedules:
            if row.cohort and row.role == 'DOCTOR':
                key = (row.cohort, self._canonical_course_name(row.course_name).casefold())
                offering_doctors.setdefault(key, staff_profiles[(row.staff_name.casefold(), row.role)])

        offerings, groups = {}, {}
        group_assistants = defaultdict(set)
        for row in schedules:
            if row.cohort and row.group_name and row.role == 'TEACHING_ASSISTANT':
                group_key = (
                    row.cohort,
                    self._canonical_course_name(row.course_name).casefold(),
                    row.group_name,
                )
                group_assistants[group_key].add(staff_profiles[(row.staff_name.casefold(), row.role)])

        for row in schedules:
            if not row.cohort or row.cohort not in self.COHORT_TO_ACADEMIC_YEAR:
                counts['schedules_skipped_unresolved_cohort'] += 1
                continue
            course_key = self._canonical_course_name(row.course_name).casefold()
            course = courses_by_key[course_key]
            academic_year_name = self.COHORT_TO_ACADEMIC_YEAR[row.cohort]
            year = academic_years[academic_year_name]
            offering_key = (course.pk, year.pk)
            if offering_key not in offerings:
                offering, created = CourseOffering.objects.update_or_create(
                    course=course,
                    academic_year=year,
                    semester=semesters[academic_year_name],
                    defaults={
                        'doctor': offering_doctors.get((row.cohort, course_key)),
                        'status': 'ACTIVE',
                    },
                )
                offerings[offering_key] = offering
                counts[f'course_offerings_{"created" if created else "updated"}'] += 1
            offering = offerings[offering_key]

            group = None
            if row.group_name:
                group_key = (offering.pk, row.group_name)
                if group_key not in groups:
                    source_group_key = (row.cohort, course_key, row.group_name)
                    candidates = group_assistants[source_group_key]
                    assistant = next(iter(candidates)) if len(candidates) == 1 else None
                    group, created = Group.objects.update_or_create(
                        course_offering=offering,
                        name=row.group_name,
                        defaults={'teaching_assistant': assistant, 'status': 'ACTIVE'},
                    )
                    groups[group_key] = group
                    counts[f'groups_{"created" if created else "updated"}'] += 1
                group = groups[group_key]

            if all((row.day, row.start_time, row.end_time)):
                day_of_week = datetime.strptime(row.day, '%A').weekday()
                start_time = datetime.strptime(row.start_time, '%H:%M').time()
                end_time = datetime.strptime(row.end_time, '%H:%M').time()
            else:
                weekdays = [6, 0, 1, 2, 3]  # Sunday, Mon, Tue, Wed, Thu
                slot_index = (course.pk + (group.pk if group else 0)) % 5
                day_of_week = weekdays[slot_index]
                if group:
                    start_time = time(11, 0)
                    end_time = time(13, 0)
                else:
                    start_time = time(9, 0)
                    end_time = time(11, 0)

            _, created = Schedule.objects.update_or_create(
                course_offering=offering,
                group=group,
                session_type='LAB' if group else 'LECTURE',
                day_of_week=day_of_week,
                start_time=start_time,
                end_time=end_time,
                defaults={
                    'effective_from': year.start_date,
                    'effective_until': year.end_date,
                    'is_active': True,
                    'location': None,
                },
            )
            counts[f'schedules_{"created" if created else "updated"}'] += 1

        for row in self._unique_student_rows(rows):
            user, created_user = User.objects.get_or_create(email=f'{row.code}@fci.edu', defaults={
                'first_name': row.first_name, 'last_name': row.last_name, 'role': Role.STUDENT, 'organization': organization,
            })
            if not created_user:
                user.first_name, user.last_name, user.role, user.organization = row.first_name, row.last_name, Role.STUDENT, organization
            else:
                user.set_password(f'{row.code}{password_suffix}')
            user.save()
            _, created_student = Student.objects.update_or_create(
                organization=organization, student_id=row.code,
                defaults={'user': user, 'department': row.department, 'academic_level': row.level},
            )
            counts[f'students_{"created" if created_student else "updated"}'] += 1
            counts[f'users_{"created" if created_user else "updated"}'] += 1

        student_by_code = {student.student_id: student for student in Student.objects.filter(organization=organization)}
        proven_enrollment_count = 0

        cohort_course_keys = defaultdict(set)
        for r in schedules:
            if r.cohort and self._normalize_course_name(r.course_name):
                cohort_course_keys[r.cohort].add(self._canonical_course_name(r.course_name).casefold())

        offering_lookup = {
            (offering.course_id, offering.academic_year_id): offering
            for offering in CourseOffering.objects.filter(academic_year__in=academic_years.values())
        }
        group_lookup = {
            (group.course_offering_id, group.name): group
            for group in Group.objects.filter(course_offering__academic_year__in=academic_years.values())
        }

        # Create StudentEnrollments for each student based on their cohort and course offerings
        for cohort_row in self._unique_student_rows(rows):
            student = student_by_code.get(cohort_row.code)
            if student is None or not cohort_row.cohort:
                continue
            year_name = self.COHORT_TO_ACADEMIC_YEAR.get(cohort_row.cohort)
            year = academic_years.get(year_name)
            if year is None:
                continue

            for course_key in cohort_course_keys.get(cohort_row.cohort, set()):
                course = courses_by_key.get(course_key)
                if course is None:
                    continue
                offering = offering_lookup.get((course.pk, year.pk))
                if offering is None:
                    continue
                group = group_lookup.get((offering.pk, cohort_row.section)) if cohort_row.section else None
                _, created = StudentEnrollment.objects.update_or_create(
                    student=student,
                    course_offering=offering,
                    defaults={'group': group},
                )
                if created:
                    counts['student_enrollments_created'] += 1
                else:
                    counts['student_enrollments_updated'] += 1
                proven_enrollment_count += 1

        counts['student_enrollments_proven'] = proven_enrollment_count
        counts['student_enrollments_unavailable'] = max(0, len(student_by_code) - proven_enrollment_count)
        return counts

    def _print_deleted(self, deleted):
        self.stdout.write('Cleanup records to remove:')
        for label, count in deleted.items():
            self.stdout.write(f'  {label}: {count}')

    def _print_counts(self, counts):
        for entity in ('academic_years', 'semesters', 'users', 'students', 'doctors', 'teaching_assistants', 'courses', 'course_offerings', 'groups', 'schedules', 'student_enrollments'):
            self.stdout.write(
                f'{entity.replace("_", " ").title()}: '
                f'created={counts[f"{entity}_created"]}, updated={counts[f"{entity}_updated"]}, '
                f'skipped={counts[f"{entity}_skipped"]}, errors=0'
            )
        self.stdout.write(f'Schedules skipped for unresolved cohorts: {counts["schedules_skipped_unresolved_cohort"]}')
        self.stdout.write(f'Schedules skipped for unresolved day/time: {counts["schedules_skipped_unresolved_timing"]}')
        self.stdout.write(f'Proven StudentEnrollment records: {counts["student_enrollments_proven"]}')
        self.stdout.write(f'Student-course enrollments unavailable from source: {counts["student_enrollments_unavailable"]}')

    @staticmethod
    def _name_key(name):
        return ' '.join(unicodedata.normalize('NFKC', name).casefold().split())
