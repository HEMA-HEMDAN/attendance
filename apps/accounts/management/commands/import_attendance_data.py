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
from datetime import date
from pathlib import Path

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
        schedules = self._read_schedule(source_dir / 'scadule.xlsx')
        staff, courses = self._derive_schedule_manifests(schedules)
        blockers = self._validate_students(rows, organization)
        blockers.extend(self._validate_manifests(staff, courses, enrollments, rows, schedules))
        missing = self._missing_manifests(source_dir)

        self._print_inventory(inventory)
        self._print_summary(rows, staff, courses, enrollments, schedules, blockers, missing, organization, options)

        if blockers:
            self.stdout.write(self.style.SUCCESS('Dry-run complete; no database writes performed.'))
            raise CommandError('Validation failed; no database changes were made.')
        if missing and not options['students_only']:
            raise CommandError('Full import is blocked because source manifests are missing.')
        if not options['execute']:
            self.stdout.write(self.style.SUCCESS('Dry-run complete; no database writes performed.'))
            return
        if not options['students_only']:
            raise CommandError('Full import is not enabled until course/group relationships are complete.')
        if not options['student_password_suffix']:
            raise CommandError('A password suffix is required for a real student import.')

        with transaction.atomic():
            if options['reset']:
                self._print_deleted(self._reset_application_data())
            counts = self._import_students(rows, organization, options['student_password_suffix'])
        self._print_counts(counts)
        self.stdout.write(self.style.SUCCESS('Import committed successfully.'))

    def _validate_options(self, options, source_dir):
        if not source_dir.is_dir():
            raise CommandError(f'Source directory does not exist: {source_dir}')
        if options['execute'] and options['dry_run']:
            raise CommandError('--execute and --dry-run cannot be used together.')
        if options['reset'] and options['confirm_reset'] != 'RESET-OLD-APPLICATION-DATA':
            raise CommandError('--reset requires --confirm-reset RESET-OLD-APPLICATION-DATA.')

    def _organization(self, slug):
        from apps.organizations.models import Organization

        try:
            return Organization.objects.get(slug=slug)
        except Organization.DoesNotExist as exc:
            raise CommandError(f'Organization does not exist: {slug}') from exc

    def _read_students(self, source_dir):
        files = sorted(
            path for path in source_dir.iterdir()
            if path.is_file() and path.suffix.lower() in self.student_extensions
            and path.name.lower() != 'scadule.xlsx'
        )
        if not files:
            raise CommandError(f'No student workbooks found in {source_dir}')
        rows, inventory = [], []
        for path in files:
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
            for row_number, values_row in enumerate(values[header_index + 1:], start=header_index + 2):
                record = dict(zip(headers, (self._clean(value) for value in values_row)))
                code, name = record.get('الكود', ''), record.get('الاسم باللغة العربية', '')
                if not re.fullmatch(r'\d{6,}', code) or not name or code in self.excluded_student_codes:
                    continue
                first_name, last_name = self._split_name(name)
                rows.append(StudentRow(
                    code, name, first_name, last_name, self._department(source_name),
                    record.get('المستوى', '') or self._level(source_name), record.get('عام الالتحاق', ''),
                    self._cohort_for_source(source_name), f'{source_name} / {sheet.title}', row_number,
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
                enrollments.append(EnrollmentRow(
                    self._cohort_for_source(row.get('source_file', '')) or row.get('academic_year', path.stem),
                    row.get('student_code', ''),
                    row.get('course_code', ''), row.get('course_name', ''),
                    row.get('group_name', ''), path.name,
                ))
        return staff, courses, enrollments

    def _read_schedule(self, path):
        if not path.is_file():
            raise CommandError(f'Schedule source does not exist: {path}')
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise CommandError('openpyxl is required to read the schedule source.') from exc
        workbook = load_workbook(path, read_only=True, data_only=True)
        sheet = workbook['Changes since v8']
        schedules = []
        for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            values = [self._clean(value) for value in row]
            if 6 <= row_number <= 12:
                level, course, group, current = values[0], values[1], '', values[4]
                schedules.append(self._parse_schedule_value(level, course, group, current, row_number, 'lecture'))
            elif 16 <= row_number <= 52 and values[0] and values[1] and values[2] and values[5].lower() != 'none':
                schedules.append(self._parse_schedule_value(values[0], values[1], values[2], values[5], row_number, 'lab'))
        workbook.close()
        return [schedule for schedule in schedules if schedule is not None]

    @staticmethod
    def _derive_schedule_manifests(schedules):
        staff_by_key = {}
        courses_by_name = {}
        for row in schedules:
            if row.staff_name:
                key = ' '.join(row.staff_name.casefold().split())
                staff_by_key.setdefault(key, {
                    'full_name': row.staff_name,
                    'first_name': row.staff_name.split()[0] if len(row.staff_name.split()) > 1 else row.staff_name,
                    'last_name': ' '.join(row.staff_name.split()[1:]),
                    'role': row.role,
                    'email': '',
                    'source': row.source,
                })
            courses_by_name.setdefault(row.course_name.casefold(), {
                'course_name': row.course_name,
                'course_code': '',
                'source': row.source,
            })
        for staff in staff_by_key.values():
            if staff['last_name']:
                staff['email'] = f'{staff["first_name"].lower()}.{staff["last_name"].lower()}@fci.edu'
        return list(staff_by_key.values()), list(courses_by_name.values())

    def _parse_schedule_value(self, level, course, group, value, row_number, session_type):
        parts = [part.strip() for part in value.split('|')]
        if len(parts) != 3:
            return ScheduleRow(self._cohort_for_level(level), level, course.rstrip(' /'), group, '', '', '', '', '', '', f'scadule.xlsx / Changes since v8 row {row_number}')
        day_time, staff_name, room = parts
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
            course_name = self._normalize_course_name(row.course_name)
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
        specs = []
        for cohort in self.cohort_by_source.values():
            start_year = int(cohort[:4])
            specs.append({
                'cohort': cohort,
                'name': cohort,
                'start_date': date(start_year, 8, 1),
                'end_date': date(start_year + 1, 7, 31),
                'is_active': date(start_year, 8, 1) <= today <= date(start_year + 1, 7, 31),
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
                self.stdout.write(self.style.WARNING(f'Duplicate identical student {code} collapsed from {len(matches)} source rows.'))
        existing_ids = set(Student.objects.filter(organization=organization).values_list('student_id', flat=True))
        for row in rows:
            if row.code in existing_ids:
                self.stdout.write(self.style.WARNING(f'Existing student will be updated: {row.code}'))
            user = User.objects.filter(email=f'{row.code}@fci.edu').first()
            if user and user.role != Role.STUDENT:
                blockers.append(f'Generated email belongs to non-student user {row.code}@fci.edu.')
        return blockers

    def _validate_manifests(self, staff, courses, enrollments, rows, schedules):
        blockers = []
        incomplete_staff = [row.get('full_name', '') for row in staff if not row.get('first_name') or not row.get('last_name')]
        if incomplete_staff:
            blockers.append(f'Incomplete staff names from source: {", ".join(incomplete_staff)}')
        invalid_roles = sorted({row.get('role', '') for row in staff if row.get('role') not in {'DOCTOR', 'TEACHING_ASSISTANT'}})
        if invalid_roles:
            blockers.append(f'Invalid or missing staff roles: {", ".join(invalid_roles)}')
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
            blockers.append(f'{missing_codes} extracted courses have no source course code; none was invented.')
        student_codes = {row.code for row in rows}
        unknown_students = sorted({row.student_code for row in enrollments if row.student_code and row.student_code not in student_codes})
        if unknown_students:
            blockers.append(f'Enrollment files reference unknown students: {", ".join(unknown_students)}')
        missing_relationships = sum(not row.course_code or not row.group_name for row in enrollments)
        if missing_relationships:
            blockers.append(f'{missing_relationships} student cohort rows have no source subject/lab membership; they are not treated as enrollments.')
        if not schedules:
            blockers.append('No current schedule relationships could be extracted from scadule.xlsx.')
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
            self.stdout.write(f'  {code}')
        self.stdout.write(f'Staff extracted: {len(staff)}; courses extracted: {len(courses)}')
        self.stdout.write(f'Schedule relationships derived: {len(schedules)}')
        self.stdout.write(f'  cohort-resolved: {sum(bool(row.cohort) for row in schedules)}')
        self.stdout.write(f'  unresolved cohort: {sum(not row.cohort for row in schedules)}')
        self.stdout.write(f'  labs/groups: {len({(row.course_name, row.group_name) for row in schedules if row.group_name})}')
        self.stdout.write(f'  unique canonical courses: {course_usage["unique_courses"]}')
        self.stdout.write(f'  course appearances across cohorts: {course_usage["appearances_across_cohorts"]}')
        self.stdout.write(f'  courses reused across multiple academic years: {course_usage["reused_across_years"]}')
        self.stdout.write(f'  duplicate courses prevented: {course_usage["duplicate_courses_prevented"]}')
        for course_name, cohorts in course_usage['course_cohorts'].items():
            if len(cohorts) > 1:
                groups = ', '.join(sorted(course_usage['course_groups'].get(course_name, []))) if course_name in course_usage['course_groups'] else 'none'
                self.stdout.write(f'  {course_name} -> cohorts={cohorts} groups={groups}')
        self.stdout.write(f'  course codes found: 0; course codes missing: {len(courses)}')
        self.stdout.write(
            f'  subject/lab enrollments mapped from student files: 0; '
            f'unresolved: {len(rows)} '
            '(student files contain cohort membership but no subject/lab membership columns)'
        )
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
            Semester.objects, AcademicYear.objects, Device.objects, AttendanceLocation.objects,
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

    def _import_students(self, rows, organization, password_suffix):
        counts = Counter()
        unique_rows = {row.code: row for row in rows}
        for row in unique_rows.values():
            user, created_user = User.objects.get_or_create(email=f'{row.code}@fci.edu', defaults={
                'first_name': row.first_name, 'last_name': row.last_name, 'role': Role.STUDENT, 'organization': organization,
            })
            if not created_user:
                user.first_name, user.last_name, user.role, user.organization = row.first_name, row.last_name, Role.STUDENT, organization
            user.set_password(f'{row.code}{password_suffix}')
            user.save()
            _, created_student = Student.objects.update_or_create(
                organization=organization, student_id=row.code,
                defaults={'user': user, 'department': row.department, 'academic_level': row.level},
            )
            counts['created' if created_student else 'updated'] += 1
        return counts

    def _print_deleted(self, deleted):
        self.stdout.write('Cleanup records to remove:')
        for label, count in deleted.items():
            self.stdout.write(f'  {label}: {count}')

    def _print_counts(self, counts):
        self.stdout.write(f'Students: created={counts["created"]}, updated={counts["updated"]}, skipped=0, errors=0')

    @staticmethod
    def _name_key(name):
        return ' '.join(unicodedata.normalize('NFKC', name).casefold().split())
