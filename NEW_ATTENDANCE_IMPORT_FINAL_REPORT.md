# New Attendance Import Final Report

## Summary

The existing guarded importer now uses the user's embedded timetable configuration in `apps/accounts/management/commands/pasted_schedule.py`; it no longer reads the deleted `scadule.xlsx`, and the implementation for this task does not read/process the old PDF or rendered images. The 12 student workbooks remain the student source. The focused dry-run succeeded with zero blocking errors and zero writes.

**No clean import or reset was executed.** The task explicitly said not to perform the destructive reset automatically. The already-populated local database was therefore left unchanged. The dry-run previews master records and clearly defers any weekly `Schedule` without a complete source day/start/end mapping.

## Sources

The importer discovered these 12 student files. Per-file source row counts below are the parser's accepted numeric/name rows before global deduplication and after excluding `26140186`:

| Source                           | Type                    | Cohort key               |           Parsed source rows |
| -------------------------------- | ----------------------- | ------------------------ | ---------------------------: |
| `Level 3 CS sections.xlsx`       | XLSX                    | `2024-CS`                |                           51 |
| `Level 3 IS sections.xlsx`       | XLSX                    | `2024-IS`                |                           55 |
| `Level 3 IT sections.xlsx`       | XLSX                    | `2024-IT`                |                           47 |
| `Level one 2026-2027.xlsx`       | XLSX                    | `2026-GENERAL`           |                          225 |
| `Level Two 2026-2027.xlsx`       | XLSX                    | `2025-GENERAL`           |                          173 |
| `اولى امن سيبرانى.xls`           | XLS                     | `2026-CYBERSECURITY`     |                           24 |
| `اولى ذكاء صناعى.xls`            | XLS                     | `2026-AI`                |                           22 |
| `تانيه امن سيبرانى.xls`          | XLS                     | `2025-CYBERSECURITY`     |                           19 |
| `تانيه ذكاء صناعى.xls`           | XLS                     | `2025-AI`                |                           19 |
| `رابعه cS.xls`                   | XLS                     | `2023-CS`                |                           31 |
| `رابعه is.xls`                   | XLS                     | `2023-IS`                |                           22 |
| `رابعه IT.xls`                   | XLS                     | `2023-IT`                |                           32 |
| Embedded timetable transcription | Supplied in user prompt | 10 page/program sections | 155 master relationship rows |

The three legacy CSV enrollment files are also read for provenance, but every row is marked `SECTION_ONLY_UNRESOLVED` and has empty course/group fields. They do not establish StudentEnrollment records.

## Student Source Results

- Candidate source rows before excluding the two conflicting-code rows: 722.
- Source rows accepted by the importer after the approved exclusion: 720.
- Unique accepted student codes: 719.
- `26140279`: duplicate same-name row across General Level 1 and AI Level 1; represented by one Student/User natural identity. Since Student has one department field and no multi-program membership relation, the importer retains the first source row deterministically (General Level 1) and dry-run warns that the source affiliation also includes AI Level 1.
- `26140186`: two different Arabic names in rows 56 and 58 of `Level one 2026-2027.xlsx`. The existing approved exclusion is retained; the code is not imported, and the dry-run reports the conflict and both source locations. No conflicting name is selected.
- Student email: `<student_code>@fci.edu`.
- Student password convention: student code concatenated with the stable configured/default importer suffix; the suffix default remains derived deterministically from the Django `SECRET_KEY` unless overridden. Passwords are stored through Django `set_password()` only.

## Academic Configuration

The previous importer convention is preserved exactly:

- AcademicYear name is the approved cohort key, scoped to the organization.
- Start date is August 1 of the key's year; end date is July 31 of the following year.
- `is_active` is calculated from the current date, as in the existing importer.
- One `Full Year` Semester is created per AcademicYear, with identical start/end dates and active state.
- CourseOffering identity remains `(Course, AcademicYear, Semester)`.

The 12 approved year records previewed by dry-run are:

| AcademicYear/cohort  | Dates                    | Active on 2026-09-28 |
| -------------------- | ------------------------ | -------------------- |
| `2023-CS`            | 2023-08-01 to 2024-07-31 | No                   |
| `2023-IS`            | 2023-08-01 to 2024-07-31 | No                   |
| `2023-IT`            | 2023-08-01 to 2024-07-31 | No                   |
| `2024-CS`            | 2024-08-01 to 2025-07-31 | No                   |
| `2024-IS`            | 2024-08-01 to 2025-07-31 | No                   |
| `2024-IT`            | 2024-08-01 to 2025-07-31 | No                   |
| `2025-GENERAL`       | 2025-08-01 to 2026-07-31 | No                   |
| `2025-AI`            | 2025-08-01 to 2026-07-31 | No                   |
| `2025-CYBERSECURITY` | 2025-08-01 to 2026-07-31 | No                   |
| `2026-GENERAL`       | 2026-08-01 to 2027-07-31 | Yes                  |
| `2026-AI`            | 2026-08-01 to 2027-07-31 | Yes                  |
| `2026-CYBERSECURITY` | 2026-08-01 to 2027-07-31 | Yes                  |

The PDF heading's “First Semester” was not used to replace the established `Full Year` Semester convention.

## Programs

The importer keeps these concepts as existing free-text program/department values and approved cohorts; it creates no new domain model:

- General
- Computer Science
- Information Systems
- Information Technology
- Artificial Intelligence
- Cybersecurity

AI and Cybersecurity remain separate. The combined timetable pages are expanded into their separate approved AI and Cybersecurity cohort offerings; no `AI + Cybersecurity` entity is created.

## Staff

Dry-run master staff preview: **15 Doctor profiles** and **15 Teaching Assistant profiles** (30 total).

Named Doctor identities from the supplied transcription: Eman El-Bakary, Amr Shawish, Asmaa El-Shehimi, Walaa Mohamed, Alaa Sameeh, Ibtisam Adel, Amr Abu Hany, Saeed Oshiba, Mohamed Abdel Latif, and Rasha Montaser.

The five non-person institutional descriptors map deterministically to the explicitly approved temporary identities:

| Descriptor                        | Temporary seed identity |
| --------------------------------- | ----------------------- |
| Science 1                         | Ahmed Samir             |
| Science 2                         | Karim Hassan            |
| Science 3                         | Omar Nabil              |
| Commerce                          | Mahmoud Nabil           |
| Information Technology department | Youssef Khaled          |

These are marked as temporary in importer configuration and are not represented as real university identities. Doctor profile titles are set as `Dr.` for these placeholders. Their source descriptor-to-placeholder mapping is kept in one configuration module for later replacement.

The 15 TA candidates are Abdallah El-Araby, Rami Sobhi, Yehia Ibrahim (source `Yehia`), Nourhan Kamal (source `Norhan`), Abdelrahman Saad, Mahmoud El-Feki, Donia Yasser, Abdelrahman Khaled, Mohamed Nafea, Mostafa Hendy, Mariam Kassem (source `Maryam`), Sohaila Ibrahim, Hoda Atef, Mohamed Yacoub, and Emad Tawfik. The incomplete forms use existing canonical identities, not new claims about official identity.

Staff emails use the existing deterministic English-name normalization and `@fci.edu`; staff passwords use the existing stable suffix convention and Django password hashing.

## Courses and Codes

- Canonical source course count in dry-run: 49.
- Each canonical Course code is generated by the existing stable organization-scoped SHA-1 policy: `COURSE-` plus the first 12 hexadecimal characters of SHA-1 over `<organization_slug>:<casefolded normalized canonical name>`.
- No source official course codes were present in the embedded timetable or existing `courses.csv`; deterministic generated codes are used only under the already-established importer policy.
- `Information retrival` normalizes to `Information Retrieval`.
- `Probability and Statisctics` normalizes to `Probability and Statistics`.
- Course names are canonicalized for capitalization and whitespace while keeping `Databases` distinct from `Database Systems`, and `Software Engineering` distinct from `Introduction to Software Engineering`.
- Shared names produce one organization-scoped canonical Course and separate CourseOfferings by cohort AcademicYear. Dry-run sees 77 unique course/cohort offering identities across the 12 cohorts.

## Offerings and Groups

- Projected CourseOfferings: 77, using existing `(course, academic_year, semester)` uniqueness.
- Source contains one co-taught lecture (Amr Abu Hany and Saeed Oshiba for Social Context Of Computing). The existing model supports one Doctor FK; the importer retains its existing deterministic first-source Doctor assignment and emits a warning rather than redesigning the schema.
- Eight offering-scoped Groups are evidenced by explicit section-number-to-TA mappings in the supplied text: Introduction To Computer Science in `2026-GENERAL`, Sections 1, 3, 4, 5, 6, 7, 8, and 9.
- Other courses list TA candidates but do not give numbered section-to-TA pairs in the supplied embedded source. No group number or student-section membership is inferred for those rows.
- Student-file section labels are not joined to timetable Groups.

## Schedules and Rooms

- Embedded timetable master relationships: 155 after expanding combined AI/Cybersecurity pages into separate approved cohorts.
- All 155 have page, level, program, cohort, canonical course, role/name, and source description.
- Valid weekly Schedule rows created by the configuration: 0. The supplied transcription does not pair a class block with a weekday and time range. No day or start/end time is fabricated.
- Six weekdays and the 09:00-17:00 hourly range are known from the transcription, but they are not attached to the 155 entries; the importer therefore defers them.
- Schedule session-type intent is represented in source roles (`DOCTOR` for lectures, `TEACHING_ASSISTANT` for section/practical records), but no recurring `Schedule` is persisted without timing.
- Room labels retained for provenance/reporting: Lab 1-8, Electronics Lab, Lecture Hall 1-2, Room 1-3, Study Room 1. They are not stored as GPS Locations.
- No AttendanceLocation, AttendanceSession, SessionOccurrence, or AttendanceRecord is created from timetable entries.

## Enrollments

- StudentEnrollment preview: 0 proven.
- Existing enrollment CSV rows contain no course code, course name, or group name and are explicitly marked `SECTION_ONLY_UNRESOLVED`; they cannot establish Student-to-CourseOffering membership.
- No student-to-section or StudentEnrollment rows are fabricated.

## Validation and Database State

- `./venv/bin/pytest -q tests/test_import_attendance_data.py`: **12 passed**.
- `./venv/bin/python manage.py check`: **no issues**.
- `./venv/bin/python manage.py import_attendance_data --organization tech-uni --dry-run`: completed; `Errors: 0`; `Dry-run complete; no database writes performed.`
- Dry-run reports 12 student source files, 720 accepted source rows, 719 unique codes, 26140186 excluded with both conflicting names and rows, 30 staff (15 Doctors and 15 TAs), five temporary Doctor placeholders, 49 canonical courses, 155 master relationships, 77 offering identities, eight explicit offering-scoped groups, zero proven StudentEnrollments, 155 deferred weekly Schedule entries, and zero locations seeded.
- The local DB remains unchanged. Read-only inspection confirmed `attendance` at `localhost:5432`; existing counts included 719 Students, 740 Users, 12 AcademicYears, 12 Semesters, 26 Courses, 24 CourseOfferings, 30 Groups, 36 existing Schedules, 4 Doctors, 15 TAs, and 1 pre-existing AttendanceLocation. ADMIN and SUPERADMIN were present.
- **No clean reset/import or second execute run was performed.** This task explicitly prohibits automatically performing the destructive reset. The displayed database counts are the prior database state, not counts produced by this configuration. Idempotency of the new configuration has not been empirically verified by an execute rerun.

## Files Changed

- `apps/accounts/management/commands/import_attendance_data.py`: existing command now loads embedded master relationships, applies canonical aliases/approved staff identities, reports provenance and deferred timing, and skips Schedule persistence unless day/start/end are all present.
- `apps/accounts/management/commands/pasted_schedule.py`: deterministic embedded configuration for the supplied transcription; no PDF, image, or XLSX is read.
- `tests/test_import_attendance_data.py`: tests now validate the embedded source, canonical aliases, cohort separation, explicitly evidenced groups, and no invented schedule timing.
- `seedingFiles/schedules/README.md`: documents the embedded schedule source and limitations.

The prior worktree deletion of `seedingFiles/scadule.xlsx` was preserved. No models, migrations, APIs, mobile code, attendance behavior, geofence behavior, or database records were changed by this task.

## Remaining Work

1. A clean local reset/seed and second-run idempotency comparison require the guarded destructive workflow, which was not run because the task explicitly forbids an automatic destructive reset.
2. Actual day/start/end for each class must be supplied as explicit row mappings before any weekly Schedule rows can be created. The supplied material states the 09:00-17:00 range but does not attach it to entries.
3. Numbered group mappings beyond the eight explicit page-1 section/TA links and any student-to-group/enrollment mappings remain absent and are intentionally not inferred.
