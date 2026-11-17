"""Excel exports for role-scoped attendance analytics."""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter


class AnalyticsExportService:
    HEADER_FILL = PatternFill('solid', fgColor='1F4E78')
    HEADER_FONT = Font(color='FFFFFF', bold=True)

    # Fake-location / CHEATING row styling
    CHEATING_ROW_FILL = PatternFill('solid', fgColor='FFE0E0')   # light red background
    CHEATING_STATUS_FONT = Font(color='CC0000', bold=True)        # dark red bold text
    FAKE_LOC_YES_FONT = Font(color='CC0000', bold=True)           # dark red for YES cell

    @classmethod
    def _workbook(cls, title, headers, rows, percentage_columns=(), cheating_status_col=None, fake_loc_col=None):
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
            # Highlight entire row red if this is a CHEATING record
            if cheating_status_col:
                status_cell = row[cheating_status_col - 1]  # 1-indexed → 0-indexed
                if status_cell.value == 'CHEATING':
                    for cell in row:
                        cell.fill = cls.CHEATING_ROW_FILL
                    status_cell.font = cls.CHEATING_STATUS_FONT
            # Bold red the Fake Location "YES" cell
            if fake_loc_col:
                fake_cell = row[fake_loc_col - 1]  # 1-indexed → 0-indexed
                if fake_cell.value and str(fake_cell.value).startswith('YES'):
                    fake_cell.font = cls.FAKE_LOC_YES_FONT
        output = BytesIO()
        workbook.save(output)
        output.seek(0)
        return output

    @classmethod
    def course_summary(cls, rows):
        headers = [
            'Student ID', 'Student Name', 'Group', 'Eligible Sessions',
            'Present', 'Late', 'Excused', 'Cheating / Invalid', 'Absent', 'Attendance Rate',
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
            'Fake Location Detected',
        ]
        values = [[
            row['student_id'], row['student_name'], row['group'], row['status'],
            row['attendance_time'], row['distance_from_session_location'], row['location_accuracy'],
            'YES ⚠️ — Used Fake Location' if row.get('mock_location_detected') else 'No',
        ] for row in rows]
        # Status=col 4, Fake Location=col 8
        return cls._workbook(
            'Session Attendance', headers, values,
            cheating_status_col=4, fake_loc_col=8,
        ).getvalue()

    @classmethod
    def student_history(cls, rows):
        headers = [
            'Date', 'Course', 'Group', 'Session Type', 'Session ID', 'Status',
            'Attendance Time', 'Distance From Session Location', 'Location Accuracy',
            'Fake Location Detected',
        ]
        values = [[
            row['date'], row['course'], row['group'], row['session_type'], row['session_id'],
            row['status'], row['attendance_time'], row['distance_from_session_location'],
            row['location_accuracy'],
            'YES ⚠️ — Used Fake Location' if row.get('mock_location_detected') else 'No',
        ] for row in rows]
        # Status=col 6, Fake Location=col 10
        return cls._workbook(
            'Attendance Details', headers, values,
            cheating_status_col=6, fake_loc_col=10,
        ).getvalue()

