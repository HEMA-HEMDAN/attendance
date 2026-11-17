"""
Dynamic Excel Template Generator for Student Import.

Creates a multi-tab .xlsx workbook:
  - Tab 1: "Student Roster" with styled headers and example rows
  - Tab 2: "Reference Data" populated with current active Courses, Semesters, and Groups
"""

import io
from django.http import HttpResponse
from django.utils.text import slugify

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from apps.courses.models import CourseOffering
from apps.groups.models import Group


class StudentTemplateBuilder:
    @classmethod
    def generate_template(cls, organization):
        wb = openpyxl.Workbook()

        # ── Tab 1: Student Roster ──────────────────────────────────────────
        ws = wb.active
        ws.title = "Student Roster"

        headers = [
            'student_id', 'full_name', 'email', 'department',
            'academic_level', 'section', 'phone', 'personal_email'
        ]
        sample_rows = [
            ['26140001', 'أحمد محمد علي كمال', '', 'Artificial Intelligence', 'Level 1', '1', '01012345678', 'ahmed@gmail.com'],
            ['26140002', 'سارة حسن إبراهيم السيد', '', 'Artificial Intelligence', 'Level 1', '2', '01198765432', 'sara@gmail.com'],
        ]

        header_font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
        header_fill = PatternFill(start_color='1E3A8A', end_color='1E3A8A', fill_type='solid')
        header_align = Alignment(horizontal='center', vertical='center')
        thin_border = Border(
            left=Side(style='thin', color='E2E8F0'),
            right=Side(style='thin', color='E2E8F0'),
            top=Side(style='thin', color='E2E8F0'),
            bottom=Side(style='thin', color='E2E8F0')
        )

        ws.append(headers)
        ws.row_dimensions[1].height = 28

        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            cell.border = thin_border

        sample_font = Font(name='Calibri', size=10, italic=True, color='475569')
        for row_idx, r in enumerate(sample_rows, start=2):
            ws.append(r)
            ws.row_dimensions[row_idx].height = 22
            for col_idx in range(1, len(headers) + 1):
                c = ws.cell(row=row_idx, column=col_idx)
                c.font = sample_font
                c.border = thin_border

        for col in ws.columns:
            m_len = max(len(str(cell.value or '')) for cell in col)
            ws.column_dimensions[get_column_letter(col[0].column)].width = max(m_len + 4, 16)

        # ── Tab 2: Reference Values ─────────────────────────────────────────
        ref_ws = wb.create_sheet(title="Reference Data")
        ref_ws.append(['Course Code', 'Course Name', 'Academic Year', 'Semester', 'Available Groups/Sections'])

        ref_header_fill = PatternFill(start_color='334155', end_color='334155', fill_type='solid')
        for col_idx in range(1, 6):
            c = ref_ws.cell(row=1, column=col_idx)
            c.font = header_font
            c.fill = ref_header_fill
            c.alignment = header_align

        offerings = CourseOffering.objects.filter(
            course__organization=organization
        ).select_related('course', 'academic_year', 'semester').prefetch_related('groups')

        for off in offerings:
            groups_str = ', '.join(g.name for g in off.groups.all()) or 'Lecture only'
            ref_ws.append([
                off.course.code,
                off.course.name,
                off.academic_year.name,
                off.semester.name,
                groups_str
            ])

        for col in ref_ws.columns:
            m_len = max(len(str(cell.value or '')) for cell in col)
            ref_ws.column_dimensions[get_column_letter(col[0].column)].width = max(m_len + 4, 16)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        filename = f"student_import_template_{slugify(organization.slug)}.xlsx"
        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
