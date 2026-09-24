"""Excel exports for role-scoped attendance analytics."""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter


class AnalyticsExportService:
    HEADER_FILL = PatternFill('solid', fgColor='1F4E78')
    HEADER_FONT = Font(color='FFFFFF', bold=True)

    @classmethod
    def _workbook(cls, title, headers, rows, percentage_columns=()):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = title
        sheet.append(headers)
        for cell in sheet[1]:
            cell.fill = cls.HEADER_FILL
            cell.font = cls.HEADER_FONT
        for row in rows:
            sheet.append(row)
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
        for column_cells in sheet.columns:
            width = max(len(str(cell.value or '')) for cell in column_cells[:100]) + 2
            sheet.column_dimensions[get_column_letter(column_cells[0].column)].width = min(max(width, 12), 36)
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                if cell.column in percentage_columns:
                    cell.number_format = '0%'
        output = BytesIO()
        workbook.save(output)
        output.seek(0)
        return output

    @classmethod
    def course_summary(cls, rows):
        headers = [
            'Student ID', 'Student Name', 'Group', 'Eligible Sessions',
            'Present', 'Late', 'Excused', 'Cheating', 'Absent', 'Attendance Rate',
        ]
        values = [
            [
                row['student_id'], row['student_name'], row['group'], row['eligible_sessions'],
                row['present'], row['late'], row['excused'], row['cheating'], row['absent'],
                row['attendance_rate'] / 100,
            ] for row in rows
        ]
        return cls._workbook('Attendance Summary', headers, values, percentage_columns=(10,)).getvalue()

    @classmethod
    def session_details(cls, rows):
        headers = [
            'Student ID', 'Student Name', 'Group', 'Status', 'Attendance Time',
            'Distance From Session Location', 'Location Accuracy',
        ]
        values = [[
            row['student_id'], row['student_name'], row['group'], row['status'],
            row['attendance_time'], row['distance_from_session_location'], row['location_accuracy'],
        ] for row in rows]
        return cls._workbook('Session Attendance', headers, values).getvalue()

    @classmethod
    def student_history(cls, rows):
        headers = [
            'Date', 'Course', 'Group', 'Session Type', 'Session ID', 'Status',
            'Attendance Time', 'Distance From Session Location', 'Location Accuracy',
        ]
        values = [[
            row['date'], row['course'], row['group'], row['session_type'], row['session_id'],
            row['status'], row['attendance_time'], row['distance_from_session_location'],
            row['location_accuracy'],
        ] for row in rows]
        return cls._workbook('Attendance Details', headers, values).getvalue()
