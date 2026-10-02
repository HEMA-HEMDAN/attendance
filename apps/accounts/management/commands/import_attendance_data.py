import csv
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.courses.models import AcademicYear, Course, CourseOffering, Schedule, Semester, SessionType
from apps.groups.models import Group
from apps.organizations.models import Organization
from apps.staff.models import Doctor, TeachingAssistant
from apps.students.models import Student, StudentEnrollment


DAY_NAMES = {
    'السبت': 5,
    'الأحد': 6,
    'الإثنين': 0,
    'الاثنين': 0,
    'الثلاثاء': 1,
    'الأربعاء': 2,
    'الاربعاء': 2,
    'الخميس': 3,
}
LEVEL_NAMES = {
    'الأول': '1', 'الاول': '1', 'الثاني': '2', 'الثالث': '3', 'الرابع': '4',
    '1': '1', '2': '2', '3': '3', '4': '4',
}
DEPARTMENT_NAMES = {
    'General': 'GENERAL',
    'Artificial Intelligence': 'AI',
    'Cybersecurity': 'CYBERSECURITY',
    'Computer Science': 'CS',
    'Information Systems': 'IS',
    'Information Technology': 'IT',
}
PROGRAM_TERMS = {
    'GENERAL': ('عام', 'general'),
    'AI': ('الذكاء الاصطناعي', 'ذكاء صناعى', 'ذكاء اصطناعي', 'artificial intelligence'),
    'CYBERSECURITY': ('الأمن السيبراني', 'امن سيبرانى', 'cybersecurity'),
    'CS': ('علوم الحاسب', 'computer science'),
    'IS': ('نظم المعلومات', 'information systems'),
    'IT': ('تكنولوجيا المعلومات', 'information technology'),
}
TIMETABLE_PROGRAM = re.compile(
    r'المستوى\s*(الأول|الاول|الثاني|الثالث|الرابع)\s*\(([^)]*)\)'
)


@dataclass(frozen=True)
class StudentSourceRow:
    code: str
    name: str
    department: str
    level: str
    cohort: str
    section: str
    source: str
    row_number: int


@dataclass
class StudentSeed:
    code: str
    name: str
    department: str
    level: str
    affiliations: set = field(default_factory=set)


@dataclass(frozen=True)
class ScheduleSourceRow:
    staff_name: str
    staff_role: str
    day: int
    start_time: time
    end_time: time
    course_name: str
    session_type: str
    cohorts: tuple
    sections: tuple
    room: str
    source_row: int


class Command(BaseCommand):
    help = 'Import FCI students, staff, courses, enrollments, and T1 schedules.'

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument('--execute', action='store_true')
        mode.add_argument('--dry-run', action='store_true')
        parser.add_argument('--source-dir', type=Path)
        parser.add_argument('--timetable', type=Path)
        parser.add_argument('--student-dir', type=Path)
        parser.add_argument('--cohort-map', type=Path)
        parser.add_argument('--organization', default='fci')
        parser.add_argument('--organization-name', default='FCI')
        parser.add_argument('--academic-year', default='2026/2027')
        parser.add_argument('--academic-year-start')
        parser.add_argument('--academic-year-end')
        parser.add_argument('--semester-name', default='T1')
        parser.add_argument('--semester-start', default='2026-09-20')
        parser.add_argument('--semester-end', default='2027-01-30')
        parser.add_argument('--exclude-student-code', action='append', default=[])

    def handle(self, *args, **options):
        server_dir = Path(__file__).resolve().parents[4]
        source_dir = options['source_dir'] or server_dir / 'seedingFiles'
        timetable_path = options['timetable'] or source_dir / 'timetable_damanhour_fci_2026_2027_T1.csv'
        student_dir = options['student_dir'] or source_dir / 'studentCsv'
        cohort_map_path = options['cohort_map'] or source_dir / 'cohort_map.csv'
        errors = []

        cohort_map = self._read_cohort_map(cohort_map_path, errors)
        students, student_row_count, conflicts = self._read_students(
            student_dir, cohort_map, set(options['exclude_student_code']), errors
        )
        schedules = self._read_schedule(timetable_path, cohort_map, errors)
        plan = self._build_plan(students, schedules, cohort_map, errors)
        self._print_preview(options, student_row_count, students, conflicts, schedules, plan, errors)

        if not options['execute']:
            self.stdout.write(self.style.SUCCESS('Dry-run complete; no database writes performed.'))
            return
        if errors:
            raise CommandError('Import blocked by source validation errors; correct the CSVs or explicitly exclude conflicting student codes.')

        year_start = self._parse_date(options['academic_year_start'], 'academic-year-start')
        year_end = self._parse_date(options['academic_year_end'], 'academic-year-end')
        semester_start = self._parse_date(options['semester_start'], 'semester-start')
        semester_end = self._parse_date(options['semester_end'], 'semester-end')
        if year_start is None or year_end is None:
            raise CommandError('Execute requires --academic-year-start and --academic-year-end.')
        if year_start > semester_start or year_end < semester_end or year_start > year_end:
            raise CommandError('Academic-year dates must contain the full semester date range.')

        try:
            with transaction.atomic():
                organization, _ = Organization.objects.get_or_create(
                    slug=options['organization'],
                    defaults={'name': options['organization_name'], 'timezone': 'Africa/Cairo'},
                )
                if organization.timezone != 'Africa/Cairo':
                    organization.timezone = 'Africa/Cairo'
                    organization.save(update_fields=['timezone', 'updated_at'])

                today = timezone.localdate()
                academic_year, _ = AcademicYear.objects.update_or_create(
                    organization=organization,
                    name=options['academic_year'],
                    defaults={
                        'start_date': year_start,
                        'end_date': year_end,
                        'is_active': year_start <= today <= year_end,
                    },
                )
                semester, _ = Semester.objects.update_or_create(
                    academic_year=academic_year,
                    name=options['semester_name'],
                    defaults={
                        'organization': organization,
                        'start_date': semester_start,
                        'end_date': semester_end,
                        'is_active': semester_start <= today <= semester_end,
                    },
                )
                staff_profiles = self._save_staff(organization, plan['staff'])
                student_profiles = self._save_students(organization, students)
                courses, offerings = self._save_courses(
                    organization, academic_year, semester, plan, staff_profiles
                )
                groups = self._save_groups(offerings, plan, staff_profiles, cohort_map)
                self._save_schedules(offerings, groups, plan, semester)
                enrollment_count, unmatched = self._save_enrollments(
                    student_profiles, offerings, groups, students, plan
                )
        except IntegrityError as exc:
            raise CommandError(f'Import rolled back because of a database constraint: {exc}') from exc

        self.stdout.write(self.style.SUCCESS(
            f'Import complete: {len(student_profiles)} students, {len(courses)} courses, '
            f'{len(offerings)} offerings, {len(groups)} groups, {enrollment_count} enrollments.'
        ))
        if unmatched:
            self.stdout.write(self.style.WARNING(
                f'{unmatched} enrollments have no matching timetable section group; '
                'their course enrollment was retained with no group assignment.'
            ))

    @staticmethod
    def _parse_date(value, option_name):
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise CommandError(f'--{option_name} must use YYYY-MM-DD.') from exc

    @staticmethod
    def _read_cohort_map(path, errors):
        if not path.exists():
            errors.append(f'Missing cohort map: {path}')
            return {}
        result = {}
        required = {'level', 'department', 'cohort_key', 'label'}
        try:
            with path.open(encoding='utf-8-sig', newline='') as source:
                reader = csv.DictReader(source)
                if not required.issubset(reader.fieldnames or []):
                    errors.append(f'{path}: required columns are {", ".join(sorted(required))}')
                    return {}
                for row_number, row in enumerate(reader, 2):
                    level = LEVEL_NAMES.get((row.get('level') or '').strip())
                    department = (row.get('department') or '').strip()
                    key = (level, department)
                    if not level or department not in DEPARTMENT_NAMES.values():
                        errors.append(f'{path}:{row_number}: invalid level or department')
                        continue
                    if key in result:
                        errors.append(f'{path}:{row_number}: duplicate level/department mapping {key}')
                        continue
                    result[key] = {
                        'cohort_key': (row.get('cohort_key') or '').strip(),
                        'label': (row.get('label') or '').strip(),
                    }
        except OSError as exc:
            errors.append(f'Cannot read cohort map {path}: {exc}')
        return result

    def _read_students(self, directory, cohort_map, excluded_codes, errors):
        paths = sorted(directory.glob('*.csv')) if directory.exists() else []
        if not paths:
            errors.append(f'No student CSV files found in {directory}')
            return [], 0, []
        by_code = defaultdict(list)
        row_count = 0
        required = {'student_code', 'student_name_ar', 'level', 'section', 'department'}
        for path in paths:
            try:
                with path.open(encoding='utf-8-sig', newline='') as source:
                    reader = csv.DictReader(source)
                    headers = set(reader.fieldnames or [])
                    if not required.issubset(headers):
                        errors.append(f'{path}: missing columns {", ".join(sorted(required - headers))}')
                        continue
                    for row_number, row in enumerate(reader, 2):
                        row_count += 1
                        code = (row.get('student_code') or '').strip()
                        name = ' '.join((row.get('student_name_ar') or '').split())
                        level = LEVEL_NAMES.get((row.get('level') or '').strip())
                        department = DEPARTMENT_NAMES.get((row.get('department') or '').strip())
                        cohort = cohort_map.get((level, department), {})
                        section = self._section_number(row.get('section') or '')
                        if not code or not name or not cohort or not section:
                            errors.append(f'{path.name}:{row_number}: invalid student code/name/cohort/section')
                            continue
                        by_code[code].append(StudentSourceRow(
                            code, name, department, level, cohort['cohort_key'], section,
                            path.name, row_number,
                        ))
            except OSError as exc:
                errors.append(f'Cannot read student file {path}: {exc}')

        conflicts = []
        students = []
        for code, rows in sorted(by_code.items()):
            if len({row.name.casefold() for row in rows}) > 1:
                conflicts.append(code)
                if code not in excluded_codes:
                    locations = ', '.join(f'{row.source}:{row.row_number}' for row in rows)
                    errors.append(f'Conflicting names for student {code} ({locations}); review and pass --exclude-student-code {code}.')
                continue
            if code in excluded_codes:
                continue
            affiliations = {(row.cohort, row.section) for row in rows}
            sections_by_cohort = defaultdict(set)
            for cohort, section in affiliations:
                sections_by_cohort[cohort].add(section)
            conflicting = [cohort for cohort, sections in sections_by_cohort.items() if len(sections) > 1]
            if conflicting:
                errors.append(f'Student {code} has multiple sections in cohort(s) {", ".join(conflicting)}.')
                continue
            first = rows[0]
            students.append(StudentSeed(code, first.name, first.department, first.level, affiliations))
        for code in sorted(set(excluded_codes) - set(conflicts)):
            errors.append(f'Excluded student code {code} is not a conflicting duplicate in the source data.')
        return students, row_count, conflicts

    @staticmethod
    def _section_number(value):
        match = re.search(r'\d+', value or '')
        return match.group(0) if match else ''

    @staticmethod
    def _program_departments(value):
        result = []
        for arabic_level, inside in TIMETABLE_PROGRAM.findall(value or ''):
            level = LEVEL_NAMES[arabic_level]
            for part in re.split(r'[/،]', inside):
                normalized = part.casefold()
                for department, terms in PROGRAM_TERMS.items():
                    if any(term.casefold() in normalized for term in terms):
                        result.append((level, department))
        return list(dict.fromkeys(result))

    def _read_schedule(self, path, cohort_map, errors):
        if not path.exists():
            errors.append(f'Missing timetable CSV: {path}')
            return []
        required = {'المدرس', 'اليوم', 'من', 'إلى', 'المستوى / البرنامج', 'المقرر', 'النوع', 'السكشن', 'القاعة / المعمل'}
        rows = []
        try:
            with path.open(encoding='utf-8-sig', newline='') as source:
                reader = csv.DictReader(source)
                if not required.issubset(reader.fieldnames or []):
                    errors.append(f'{path}: timetable is missing expected Arabic columns')
                    return []
                for row_number, row in enumerate(reader, 2):
                    try:
                        cohorts = []
                        for key in self._program_departments(row['المستوى / البرنامج']):
                            mapped = cohort_map.get(key)
                            if not mapped:
                                raise ValueError(f'program/level has no cohort-map entry: {key}')
                            cohorts.append(mapped['cohort_key'])
                        cohorts = tuple(dict.fromkeys(cohorts))
                        if not cohorts:
                            raise ValueError('program label did not resolve to a cohort')
                        day_name = (row['اليوم'] or '').strip()
                        if day_name not in DAY_NAMES:
                            raise ValueError(f'unknown Arabic weekday {day_name!r}')
                        raw_type = (row['النوع'] or '').strip()
                        if raw_type == 'محاضرة':
                            session_type = SessionType.LECTURE
                        elif raw_type == 'سكشن':
                            session_type = SessionType.LAB
                        else:
                            raise ValueError(f'unknown session type {raw_type!r}')
                        start = datetime.strptime((row['من'] or '').strip(), '%H:%M').time()
                        end = datetime.strptime((row['إلى'] or '').strip(), '%H:%M').time()
                        if end <= start:
                            raise ValueError('session end must be after start')
                        staff_name, role = self._parse_staff((row['المدرس'] or '').strip())
                        course_name = ' '.join((row['المقرر'] or '').split())
                        if not course_name:
                            raise ValueError('course name is empty')
                        sections = tuple(dict.fromkeys(re.findall(r'\d+', row['السكشن'] or '')))
                        if session_type == SessionType.LAB and not sections:
                            raise ValueError('section row has no numeric section')
                        rows.append(ScheduleSourceRow(
                            staff_name, role, DAY_NAMES[day_name], start, end,
                            course_name, session_type, cohorts, sections,
                            ' '.join((row['القاعة / المعمل'] or '').split()), row_number,
                        ))
                    except (ValueError, KeyError) as exc:
                        errors.append(f'{path.name}:{row_number}: {exc}')
        except OSError as exc:
            errors.append(f'Cannot read timetable {path}: {exc}')
        return rows

    @staticmethod
    def _parse_staff(value):
        match = re.match(r'^(?:(?:أ|ا)\.?\s*)?(د\.?|دكتور(?:ة)?|م\.?|مهندس(?:ة)?)\s*', value)
        if not match:
            raise ValueError(f'instructor has no recognized Doctor/TA title: {value!r}')
        role = Role.DOCTOR if match.group(1).startswith('د') else Role.TEACHING_ASSISTANT
        name = ' '.join(value[match.end():].split())
        if not name:
            raise ValueError('instructor name is empty')
        return name, role

    def _build_plan(self, students, schedules, cohort_map, errors):
        slots = defaultdict(set)
        for row in schedules:
            for cohort in row.cohorts:
                slots[(row.course_name.casefold(), cohort)].add(
                    (row.day, row.start_time, row.end_time, row.session_type)
                )
        variant_by_cohort = {}
        variants = {}
        for (course_key, cohort), course_slots in slots.items():
            signature = tuple(sorted(course_slots))
            variant_key = (course_key, signature)
            variant_by_cohort[(course_key, cohort)] = variant_key
            variant = variants.setdefault(variant_key, {
                'course_key': course_key, 'signature': signature,
                'cohorts': set(), 'rows': [], 'course_name': '',
            })
            variant['cohorts'].add(cohort)
        for row in schedules:
            for cohort in row.cohorts:
                variant = variants[variant_by_cohort[(row.course_name.casefold(), cohort)]]
                if not variant['course_name']:
                    variant['course_name'] = row.course_name
                variant['rows'].append((row, cohort))

        variants_by_title = defaultdict(set)
        for key, variant in variants.items():
            variants_by_title[variant['course_key']].add(key)
        cohort_labels = {item['cohort_key']: item['label'] for item in cohort_map.values()}
        for variant in variants.values():
            if len(variants_by_title[variant['course_key']]) > 1:
                labels = ' / '.join(sorted(cohort_labels.get(c, c) for c in variant['cohorts']))
                variant['display_name'] = f"{variant['course_name']} ({labels})"
            else:
                variant['display_name'] = variant['course_name']
            variant['code'] = self._course_code(variant['course_key'], variant['signature'])

        student_cohorts = {cohort for student in students for cohort, _section in student.affiliations}
        timetable_cohorts = {cohort for _title, cohort in slots}
        for cohort in sorted(student_cohorts - timetable_cohorts):
            errors.append(f'Roster cohort {cohort} has students but no timetable rows.')

        staff = {}
        groups = {}
        schedule_slots = {}
        for variant_key, variant in variants.items():
            doctors = set()
            for row, cohort in variant['rows']:
                staff[(row.staff_role, row.staff_name.casefold())] = {
                    'role': row.staff_role, 'name': row.staff_name,
                }
                if row.staff_role == Role.DOCTOR:
                    doctors.add(row.staff_name)
                if row.session_type == SessionType.LAB:
                    for section in row.sections:
                        group_key = (variant_key, cohort, section)
                        group = groups.setdefault(group_key, {
                            'cohort': cohort, 'section': section, 'tas': set(),
                        })
                        if row.staff_role == Role.TEACHING_ASSISTANT:
                            group['tas'].add(row.staff_name)
                        schedule_key = (
                            variant_key, cohort, section, row.day, row.start_time,
                            row.end_time, row.session_type,
                        )
                        schedule_slots.setdefault(schedule_key, set()).add(row.room)
                else:
                    schedule_key = (
                        variant_key, None, None, row.day, row.start_time,
                        row.end_time, row.session_type,
                    )
                    schedule_slots.setdefault(schedule_key, set()).add(row.room)
            variant['doctors'] = tuple(sorted(doctors))

        enrollments = []
        unmatched = 0
        for student in students:
            enrolled_variants = set()
            for cohort, section in sorted(student.affiliations):
                for variant_key, variant in variants.items():
                    if cohort not in variant['cohorts']:
                        continue
                    if variant_key in enrolled_variants:
                        continue
                    enrolled_variants.add(variant_key)
                    has_groups = any(k[0] == variant_key and k[1] == cohort for k in groups)
                    group_key = (variant_key, cohort, section)
                    assigned_group = group_key if group_key in groups else None
                    if has_groups and assigned_group is None:
                        unmatched += 1
                    enrollments.append((student.code, variant_key, assigned_group))

        return {
            'variants': variants, 'staff': staff, 'groups': groups,
            'schedule_slots': schedule_slots, 'enrollments': enrollments,
            'unmatched_group_assignments': unmatched,
        }

    @staticmethod
    def _course_code(course_key, signature):
        slot_text = '|'.join(
            f'{day}:{start.isoformat()}-{end.isoformat()}:{session_type}'
            for day, start, end, session_type in signature
        )
        digest = hashlib.sha1(f'{course_key}|{slot_text}'.encode('utf-8')).hexdigest()[:12]
        return f'FCI-{digest.upper()}'

    def _print_preview(self, options, row_count, students, conflicts, schedules, plan, errors):
        self.stdout.write(f"Organization: {options['organization']} (Africa/Cairo)")
        self.stdout.write(f"T1: {options['semester_start']} to {options['semester_end']}")
        self.stdout.write(f'Student rows: {row_count}; unique students: {len(students)}')
        self.stdout.write(f'Timetable rows: {len(schedules)}; course variants: {len(plan["variants"])}')
        self.stdout.write(
            f'Planned staff: {len(plan["staff"])}; groups: {len(plan["groups"])}; '
            f'schedules: {len(plan["schedule_slots"])}; enrollments: {len(plan["enrollments"])}'
        )
        if conflicts:
            self.stdout.write(self.style.WARNING('Conflicting student codes: ' + ', '.join(conflicts)))
        if plan['unmatched_group_assignments']:
            self.stdout.write(self.style.WARNING(
                f"Unmatched student-to-section assignments: {plan['unmatched_group_assignments']} "
                '(enrollments retained without a group).'
            ))
        for error in errors:
            self.stdout.write(self.style.ERROR(f'BLOCKING: {error}'))

    @staticmethod
    def _name_parts(full_name):
        parts = full_name.split()
        return parts[0], ' '.join(parts[1:]) or '-'

    @staticmethod
    def _staff_email(role, name):
        digest = hashlib.sha256(f'{role}:{name.casefold()}'.encode('utf-8')).hexdigest()[:12]
        prefix = 'doctor' if role == Role.DOCTOR else 'ta'
        return f'{prefix}-{digest}@fci.edu'

    @classmethod
    def _get_or_create_user(cls, email, role, organization, name, password):
        first_name, last_name = cls._name_parts(name)
        user = User.objects.filter(email=email).first()
        if user:
            if user.organization_id != organization.id or user.role != role:
                raise CommandError(f'Email {email} is already used by a different account.')
            if (user.first_name, user.last_name) != (first_name, last_name):
                user.first_name, user.last_name = first_name, last_name
                user.save(update_fields=['first_name', 'last_name', 'updated_at'])
            return user
        return User.objects.create_user(
            email=email, password=password, first_name=first_name,
            last_name=last_name, role=role, organization=organization,
        )

    def _save_staff(self, organization, staff_data):
        profiles = {}
        for key, item in sorted(staff_data.items()):
            role, name = item['role'], item['name']
            email = self._staff_email(role, name)
            user = self._get_or_create_user(email, role, organization, name, email)
            if role == Role.DOCTOR:
                profile, _ = Doctor.objects.get_or_create(
                    user=user, defaults={'organization': organization, 'title': 'Dr.'}
                )
            else:
                profile, _ = TeachingAssistant.objects.get_or_create(
                    user=user, defaults={'organization': organization}
                )
            if profile.organization_id != organization.id:
                raise CommandError(f'Staff profile {email} belongs to another organization.')
            profiles[key] = profile
        return profiles

    def _save_students(self, organization, rows):
        profiles = {}
        for row in rows:
            email = f'{row.code}@fci.edu'
            first_name, last_name = self._name_parts(row.name)
            student = Student.objects.filter(
                organization=organization, student_id=row.code
            ).select_related('user').first()
            email_owner = User.objects.filter(email=email).first()
            if student:
                user = student.user
                if user.role != Role.STUDENT or (email_owner and email_owner.pk != user.pk):
                    raise CommandError(f'Student {row.code} conflicts with an existing account.')
                user.email, user.first_name, user.last_name = email, first_name, last_name
                user.save(update_fields=['email', 'first_name', 'last_name', 'updated_at'])
                student.department = row.department
                student.academic_level = f'Level {row.level}'
                student.save(update_fields=['department', 'academic_level', 'updated_at'])
            else:
                user = email_owner
                if user:
                    if user.organization_id != organization.id or user.role != Role.STUDENT:
                        raise CommandError(f'Email {email} is already used by a different account.')
                    user.first_name, user.last_name = first_name, last_name
                    user.save(update_fields=['first_name', 'last_name', 'updated_at'])
                else:
                    user = User.objects.create_user(
                        email=email, password=f'{row.code}#Fci!',
                        first_name=first_name, last_name=last_name,
                        role=Role.STUDENT, organization=organization,
                    )
                student = Student.objects.create(
                    user=user, organization=organization, student_id=row.code,
                    department=row.department, academic_level=f'Level {row.level}',
                )
            profiles[row.code] = student
        return profiles

    def _save_courses(self, organization, academic_year, semester, plan, staff_profiles):
        courses, offerings = {}, {}
        variants = sorted(plan['variants'].items(), key=lambda item: item[1]['code'])
        for variant_key, variant in variants:
            departments = {cohort.rsplit('-', 1)[-1] for cohort in variant['cohorts']}
            department = next(iter(departments)) if len(departments) == 1 else ''
            course, _ = Course.objects.update_or_create(
                organization=organization,
                code=variant['code'],
                defaults={'name': variant['display_name'], 'department': department},
            )
            doctor_names = variant['doctors']
            doctor = staff_profiles.get((Role.DOCTOR, doctor_names[0].casefold())) if doctor_names else None
            offering, _ = CourseOffering.objects.update_or_create(
                course=course,
                academic_year=academic_year,
                semester=semester,
                defaults={'doctor': doctor},
            )
            courses[variant_key], offerings[variant_key] = course, offering
        return courses, offerings

    def _save_groups(self, offerings, plan, staff_profiles, cohort_map):
        groups = {}
        labels = {item['cohort_key']: item['label'] for item in cohort_map.values()}
        for key, item in sorted(plan['groups'].items(), key=lambda pair: str(pair[0])):
            variant_key, cohort, section = key
            name = f'{labels.get(cohort, cohort)} Section {section}'
            ta_names = sorted(item['tas'])
            ta = staff_profiles.get((Role.TEACHING_ASSISTANT, ta_names[0].casefold())) if ta_names else None
            if len(ta_names) > 1:
                self.stdout.write(self.style.WARNING(f'{name} has multiple TAs; assigning {ta_names[0]}.'))
            group, _ = Group.objects.update_or_create(
                course_offering=offerings[variant_key],
                name=name,
                defaults={'teaching_assistant': ta},
            )
            groups[key] = group
        return groups

    def _save_schedules(self, offerings, groups, plan, semester):
        for key, rooms in plan['schedule_slots'].items():
            variant_key, cohort, section, day, start, end, session_type = key
            group = groups.get((variant_key, cohort, section)) if section else None
            defaults = {
                'room_label': ' / '.join(sorted(room for room in rooms if room)),
                'effective_from': semester.start_date,
                'effective_until': semester.end_date,
                'is_active': True,
            }
            schedule = Schedule.objects.filter(
                course_offering=offerings[variant_key], group=group,
                session_type=session_type, day_of_week=day,
                start_time=start, end_time=end,
            ).first()
            if schedule:
                for field_name, value in defaults.items():
                    setattr(schedule, field_name, value)
                schedule.save(update_fields=[*defaults, 'updated_at'])
            else:
                Schedule.objects.create(
                    course_offering=offerings[variant_key], group=group,
                    session_type=session_type, day_of_week=day,
                    start_time=start, end_time=end, **defaults,
                )

    def _save_enrollments(self, student_profiles, offerings, groups, students, plan):
        enrollments = []
        for code, variant_key, group_key in plan['enrollments']:
            enrollments.append(StudentEnrollment(
                student=student_profiles[code],
                course_offering=offerings[variant_key],
                group=groups.get(group_key) if group_key else None,
            ))
        StudentEnrollment.objects.bulk_create(enrollments, ignore_conflicts=True, batch_size=1000)
        return len(enrollments), plan['unmatched_group_assignments']