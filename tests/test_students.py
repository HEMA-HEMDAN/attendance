"""
Student provisioning tests — create, import CSV, duplicate protection.
"""

import io
import pytest
from rest_framework.test import APIClient
from tests.factories import OrganizationFactory, AdminUserFactory, GroupFactory, StudentFactory


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def setup():
    org = OrganizationFactory()
    admin = AdminUserFactory(organization=org)
    group = GroupFactory(organization=org)
    return org, admin, group


@pytest.mark.django_db
class TestStudentCreate:
    def test_create_student(self, client, setup):
        org, admin, group = setup
        client.force_authenticate(user=admin)
        response = client.post('/api/v1/students/', {
            'student_id': 'STU001',
            'first_name': 'Ahmed',
            'last_name': 'Ali',
            'email': 'ahmed@example.com',
            'group': group.id,
        })
        assert response.status_code == 201

    def test_duplicate_student_id(self, client, setup):
        org, admin, group = setup
        StudentFactory(organization=org, student_id='STU001', group=group)
        client.force_authenticate(user=admin)
        response = client.post('/api/v1/students/', {
            'student_id': 'STU001',
            'first_name': 'Sara',
            'last_name': 'Hassan',
            'email': 'sara@example.com',
            'group': group.id,
        })
        assert response.status_code == 400

    def test_deactivate_student(self, client, setup):
        org, admin, group = setup
        student = StudentFactory(organization=org, group=group)
        client.force_authenticate(user=admin)
        response = client.delete(f'/api/v1/students/{student.id}/')
        assert response.status_code == 204
        student.refresh_from_db()
        assert student.status == 'ARCHIVED'


@pytest.mark.django_db
class TestCSVImport:
    def _make_csv(self, rows: list[str]) -> io.BytesIO:
        content = 'student_id,first_name,last_name,email,group\n' + '\n'.join(rows)
        buf = io.BytesIO(content.encode())
        buf.name = 'students.csv'
        return buf

    def test_validate_valid_csv(self, client, setup):
        org, admin, group = setup
        csv_file = self._make_csv([
            f'20260001,Ahmed,Ali,ahmed@example.com,{group.name}',
            f'20260002,Sara,Hassan,sara@example.com,{group.name}',
        ])
        client.force_authenticate(user=admin)
        response = client.post(
            '/api/v1/students/import/validate/',
            {'file': csv_file},
            format='multipart',
        )
        assert response.status_code == 200
        assert response.data['valid_count'] == 2
        assert response.data['invalid_count'] == 0

    def test_validate_detects_missing_email(self, client, setup):
        org, admin, group = setup
        csv_file = self._make_csv(['20260001,Ahmed,Ali,,Group A'])
        client.force_authenticate(user=admin)
        response = client.post(
            '/api/v1/students/import/validate/',
            {'file': csv_file},
            format='multipart',
        )
        assert response.status_code == 200
        assert response.data['invalid_count'] == 1

    def test_execute_import(self, client, setup):
        org, admin, group = setup
        csv_file = self._make_csv([
            f'20260003,Omar,Mostafa,omar@example.com,{group.name}',
        ])
        client.force_authenticate(user=admin)
        response = client.post(
            '/api/v1/students/import/execute/',
            {'file': csv_file},
            format='multipart',
        )
        assert response.status_code == 201
        assert response.data['imported'] == 1

    def test_import_detects_duplicates(self, client, setup):
        org, admin, group = setup
        StudentFactory(organization=org, student_id='20260010', group=group)
        csv_file = self._make_csv([
            f'20260010,Existing,Student,existing@example.com,{group.name}',
            f'20260011,New,Student,new@example.com,{group.name}',
        ])
        client.force_authenticate(user=admin)
        response = client.post(
            '/api/v1/students/import/execute/',
            {'file': csv_file},
            format='multipart',
        )
        assert response.status_code == 201
        assert response.data['imported'] == 1
        assert response.data['skipped_duplicates'] == 1

    def test_non_csv_rejected(self, client, setup):
        org, admin, group = setup
        txt_file = io.BytesIO(b'not a csv')
        txt_file.name = 'file.txt'
        client.force_authenticate(user=admin)
        response = client.post(
            '/api/v1/students/import/validate/',
            {'file': txt_file},
            format='multipart',
        )
        assert response.status_code == 400
