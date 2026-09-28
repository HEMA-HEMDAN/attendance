"""Master schedule relationships supplied in the user's pasted transcription.

No day/time pair is inferred from the flattened transcription. Entries below
therefore describe course, staff, program/cohort, and explicitly numbered
sections only; the importer must not persist them as weekly Schedule rows.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PastedScheduleEntry:
    page: int
    level: str
    program: str
    cohort: str
    course_name: str
    role: str
    staff_name: str
    group_name: str = ''
    source: str = ''


TEMPORARY_DOCTORS = {
    'Science 1': 'Dr Ahmed Samir',
    'Science 2': 'Dr Karim Hassan',
    'Science 3': 'Dr Omar Nabil',
    'Commerce': 'Dr Mahmoud Nabil',
    'Information Technology department': 'Dr Youssef Khaled',
}
TEMPORARY_DOCTOR_NAMES = {
    value[3:] if value.startswith('Dr ') else value
    for value in TEMPORARY_DOCTORS.values()
}

DOCTOR_ALIASES = {
    'Science': 'Science 1',
    'د/منتدب من كلية علوم': 'Science 1',
    'د/منتدب من كلية علوم 1': 'Science 1',
    'د/منتدب من كلية علوم 2': 'Science 2',
    'د/منتدب من كلية علوم 3': 'Science 3',
    'د/منتدب من تجارة': 'Commerce',
    'Commerce descriptor': 'Commerce',
    'د/قسم تكنولوجيا المعلومات': 'Information Technology department',
    'IT department descriptor': 'Information Technology department',
    'Ibtisam Adel': 'Ibtisam Adel',
    'Asmaa El-Shehimi': 'Asmaa El-Shehimi',
    'Mohamed Abdel Latif': 'Mohamed Abdel Latif',
}

STAFF_ALIASES = {
    'Yehia': 'Yehia Ibrahim',
    'Norhan': 'Nourhan Kamal',
    'Maryam': 'Mariam Kassem',
}

# Each tuple is (canonical course, doctor names/descriptors, TA names,
# explicit section-to-TA pairs). Sections omitted by the transcription remain
# unresolved and are not synthesized.
_PAGE_COURSES = (
    (1, '1', 'General', ('2026-GENERAL',), (
        ('Electronics', ('Eman El-Bakary',), (), ()),
        ('Introduction To Computer Science', ('Amr Shawish',), (), (
            ('Section 1', 'Abdallah El-Araby'),
            ('Section 3', 'Rami Sobhi'),
            ('Section 4', 'Yehia'),
            ('Section 5', 'Abdallah El-Araby'),
            ('Section 6', 'Rami Sobhi'),
            ('Section 7', 'Yehia'),
            ('Section 8', 'Abdallah El-Araby'),
            ('Section 9', 'Rami Sobhi'),
        )),
        ('Math1', ('Science 1',), (), ()),
        ('Math 0', ('Science',), (), ()),
            ('Physics', ('Science 2',), (), ()),
        ('General English Language', ('Asmaa El-Shehimi',), (), ()),
        ('Computer Law', ('Walaa Mohamed',), (), ()),
        ('Interpersonal Communication', ('Alaa Sameeh',), (), ()),
    )),
    (2, '2', 'General', ('2025-GENERAL',), (
        ('Object Oriented Programming', ('Mohamed Abdel Latif',), (
            'Donia Yasser', 'Yehia', 'Abdelrahman Khaled', 'Abdallah El-Araby'), ()),
        ('Data Communications', ('Information Technology department',), (
            'Mahmoud El-Feki', 'Norhan', 'Mohamed Nafea'), ()),
        ('Computer Architecture', ('Rasha Montaser',), (
            'Abdelrahman Saad', 'Donia Yasser', 'Abdallah El-Araby'), ()),
        ('Databases', ('Ibtisam Adel',), ('Mohamed Nafea', 'Mostafa Hendy'), ()),
        ('Social Context Of Computing', ('Amr Abu Hany', 'Saeed Oshiba'), (), ()),
        ('Math III', ('Science 3',), (), ()),
        ('Probability and Statistics', ('Science 1',), (), ()),
    )),
    (3, '3', 'Computer Science', ('2024-CS',), (
        ('Image Processing', ('Ibtisam Adel',), ('Maryam',), ()),
        ('Digital Signal Processing', ('Eman El-Bakary',), ('Sohaila Ibrahim',), ()),
        ('Computer Graphics Fundamentals', ('Rasha Montaser',), ('Abdelrahman Khaled',), ()),
        ('Neural Networks', ('Mohamed Abdel Latif',), ('Donia Yasser',), ()),
        ('Algorithm Design and Analysis', ('Amr Shawish',), ('Mahmoud El-Feki',), ()),
        ('Software Engineering', ('Amr Abu Hany',), ('Hoda Atef',), ()),
    )),
    (4, '3', 'Information Systems', ('2024-IS',), (
        ('Decision Support Systems', ('Ibtisam Adel',), ('Maryam',), ()),
        ('Geographic Information System', ('Alaa Sameeh',), ('Mohamed Yacoub',), ()),
        ('Introduction To Data Science', ('Information Technology department',), ('Mostafa Hendy',), ()),
        ('Human Computer Interaction', ('Amr Abu Hany',), ('Hoda Atef',), ()),
        ('Software Engineering', ('Amr Abu Hany',), ('Maryam',), ()),
        ('Information Security', ('Information Technology department',), ('Mohamed Yacoub',), ()),
    )),
    (5, '3', 'Information Technology', ('2024-IT',), (
        ('Software Engineering', ('Ibtisam Adel',), ('Mahmoud El-Feki',), ()),
        ('Digital Signal Processing', ('Eman El-Bakary',), ('Sohaila Ibrahim',), ()),
        ('Image Processing', ('Information Technology department',), ('Maryam',), ()),
        ('Human Computer Interaction', ('Amr Abu Hany',), ('Mohamed Yacoub',), ()),
        ('Web Programming', ('Rasha Montaser',), ('Mostafa Hendy',), ()),
        ('Network Programming', ('Walaa Mohamed',), ('Abdelrahman Saad', 'Hoda Atef'), ()),
    )),
    (6, '4', 'Computer Science', ('2023-CS',), (
        ('Advanced Database', ('Ibtisam Adel',), ('Sohaila Ibrahim',), ()),
        ('Speech Processing', ('Eman El-Bakary',), ('Donia Yasser',), ()),
        ('Machine Learning', ('Rasha Montaser',), ('Norhan',), ()),
        ('Wireless and Mobile Computing', ('Mohamed Abdel Latif',), ('Mohamed Yacoub',), ()),
        ('Data Mining', ('Information Technology department',), ('Rami Sobhi',), ()),
        ('Programming Language Design', ('Amr Shawish',), ('Emad Tawfik',), ()),
    )),
    (7, '4', 'Information Systems', ('2023-IS',), (
        ('Advanced Database', ('Ibtisam Adel',), ('Sohaila Ibrahim',), ()),
        ('Network Analysis and Design', ('Walaa Mohamed',), ('Norhan',), ()),
        ('Enterprise Architecture', ('Walaa Mohamed',), ('Emad Tawfik',), ()),
        ('Wireless and Mobile Computing', ('Eman El-Bakary',), ('Rami Sobhi',), ()),
        ('Speech Processing', ('Information Technology department',), ('Sohaila Ibrahim',), ()),
    )),
    (8, '4', 'Information Technology', ('2023-IT',), (
        ('Advanced Database', ('Ibtisam Adel',), ('Emad Tawfik',), ()),
        ('Enterprise Architecture', ('Walaa Mohamed',), ('Emad Tawfik',), ()),
        ('Information Retrieval', ('Rasha Montaser',), ('Mohamed Yacoub',), ()),
        ('Data Mining', ('Alaa Sameeh',), ('Abdallah El-Araby',), ()),
        ('Database Administration', ('Amr Abu Hany',), ('Mohamed Nafea',), ()),
    )),
    (9, '1', 'Artificial Intelligence / Cybersecurity', ('2026-AI', '2026-CYBERSECURITY'), (
        ('Creative Thinking and Problem Solving', ('Amr Abu Hany',), (), ()),
        ('Digital Circuits', ('Eman El-Bakary',), ('Yehia',), ()),
        ('Fundamentals of Programming', ('Mohamed Abdel Latif',), ('Abdelrahman Saad', 'Yehia'), ()),
        ('Computer Networks', ('Science 1',), ('Hoda Atef',), ()),
        ('Mathematics-1', ('Science 1',), (), ()),
        ('Math 0', ('Commerce',), (), ()),
        ('Communication and Negotiation Skills', ('Walaa Mohamed',), (), ()),
        ('General English Language', ('Asmaa El-Shehimi',), (), ()),
    )),
    (10, '2', 'Artificial Intelligence / Cybersecurity', ('2025-AI', '2025-CYBERSECURITY'), (
        ('Logic Design', ('Ibtisam Adel',), ('Norhan', 'Mostafa Hendy'), ()),
        ('Database Systems', ('Ibtisam Adel',), ('Mohamed Nafea',), ()),
        ('Information Security', ('Rasha Montaser',), ('Emad Tawfik',), ()),
        ('Data Structures and Algorithms', ('Amr Abu Hany',), ('Abdelrahman Khaled',), ()),
        ('Introduction to Software Engineering', ('Science 1',), ('Mohamed Yacoub', 'Mahmoud El-Feki'), ()),
        ('Statistics and Probabilities', ('Information Technology department',), (), ()),
    )),
)

ROOM_LABELS = (
    'Lab 1', 'Lab 2', 'Lab 3', 'Lab 4', 'Lab 5', 'Lab 6', 'Lab 7', 'Lab 8',
    'Electronics Lab', 'Lecture Hall 1', 'Lecture Hall 2', 'Room 1', 'Room 2',
    'Room 3', 'Study Room 1',
)


def read_pasted_schedule_entries() -> tuple[PastedScheduleEntry, ...]:
    entries = []
    for page, level, program, cohorts, courses in _PAGE_COURSES:
        for cohort in cohorts:
            for course_name, doctors, assistants, section_assistants in courses:
                source = f'pasted timetable / page {page} / {program} / {course_name}'
                for doctor in doctors:
                    entries.append(PastedScheduleEntry(
                        page, level, program, cohort, course_name, 'DOCTOR', doctor,
                        source=source,
                    ))
                explicit_sections = dict(section_assistants)
                if explicit_sections:
                    for group_name, assistant in section_assistants:
                        entries.append(PastedScheduleEntry(
                            page, level, program, cohort, course_name,
                            'TEACHING_ASSISTANT', assistant, group_name, source,
                        ))
                else:
                    for assistant in assistants:
                        entries.append(PastedScheduleEntry(
                            page, level, program, cohort, course_name,
                            'TEACHING_ASSISTANT', assistant, source=source,
                        ))
    return tuple(entries)