"""
Students serializers — includes CSV import validation.
"""

import csv
import io
import secrets
from django.db import transaction
from rest_framework import serializers

from apps.accounts.models import User, Role
from apps.groups.models import Group
from .models import Student


class StudentSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', read_only=True)
    first_name = serializers.CharField(source='user.first_name', read_only=True)
    last_name = serializers.CharField(source='user.last_name', read_only=True)
    is_active = serializers.BooleanField(source='user.is_active', read_only=True)
    group_name = serializers.CharField(source='group.name', read_only=True, allow_null=True)

    class Meta:
        model = Student
        fields = [
            'id', 'student_id', 'email', 'first_name', 'last_name',
            'phone', 'status', 'group', 'group_name', 'is_active', 'created_at',
        ]
        read_only_fields = ['id', 'created_at', 'email', 'first_name', 'last_name', 'is_active']


class StudentCreateSerializer(serializers.Serializer):
    student_id = serializers.CharField(max_length=100)
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    group = serializers.PrimaryKeyRelatedField(
        queryset=Group.objects.none(), required=False, allow_null=True
    )
    password = serializers.CharField(write_only=True, min_length=8, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request and request.user.organization_id:
            self.fields['group'].queryset = Group.objects.filter(
                organization=request.user.organization,
                status='ACTIVE',
            )

    def validate_student_id(self, value):
        org = self.context['request'].user.organization
        if Student.objects.filter(organization=org, student_id=value).exists():
            raise serializers.ValidationError(f'Student ID {value} already exists in this organization')
        return value

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError(f'Email {value} is already registered')
        return value

    @transaction.atomic
    def create(self, validated_data):
        org = self.context['request'].user.organization
        group = validated_data.pop('group', None)
        phone = validated_data.pop('phone', '')
        password = validated_data.pop('password', None) or secrets.token_urlsafe(12)

        user = User.objects.create_user(
            email=validated_data['email'],
            password=password,
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            role=Role.STUDENT,
            organization=org,
        )
        student = Student.objects.create(
            user=user,
            organization=org,
            student_id=validated_data['student_id'],
            group=group,
            phone=phone,
        )
        return student


class CSVImportSerializer(serializers.Serializer):
    """
    Validates and imports students from CSV.

    Expected CSV columns:
      student_id, first_name, last_name, email, group (optional)

    The import is transactional: if it fails mid-way, no partial data is committed.
    """

    file = serializers.FileField()

    REQUIRED_COLUMNS = {'student_id', 'first_name', 'last_name', 'email'}

    def validate_file(self, value):
        if not value.name.endswith('.csv'):
            raise serializers.ValidationError('File must be a CSV')
        if value.size > 5 * 1024 * 1024:  # 5MB
            raise serializers.ValidationError('File too large (max 5MB)')
        return value

    def parse_and_validate(self, organization):
        """
        Returns:
          valid_rows:   list of dicts ready for import
          invalid_rows: list of {row, errors}
          duplicates:   list of rows that already exist
        """
        file = self.validated_data['file']
        content = file.read().decode('utf-8-sig')  # handle BOM
        reader = csv.DictReader(io.StringIO(content))

        # Check headers
        if not reader.fieldnames:
            raise serializers.ValidationError({'file': 'CSV appears to be empty'})

        headers = {h.strip().lower() for h in reader.fieldnames}
        missing = self.REQUIRED_COLUMNS - headers
        if missing:
            raise serializers.ValidationError(
                {'file': f'Missing required columns: {", ".join(missing)}'}
            )

        # Load existing data for fast duplicate checks
        existing_student_ids = set(
            Student.objects.filter(organization=organization).values_list('student_id', flat=True)
        )
        existing_emails = set(
            User.objects.values_list('email', flat=True)
        )
        group_map = {
            g.name.lower(): g
            for g in Group.objects.filter(organization=organization, status='ACTIVE')
        }

        valid_rows = []
        invalid_rows = []
        duplicates = []
        seen_ids = set()
        seen_emails = set()

        for i, row in enumerate(reader, start=2):  # row 1 = header
            row = {k.strip().lower(): v.strip() for k, v in row.items() if k}
            errors = []

            student_id = row.get('student_id', '')
            first_name = row.get('first_name', '')
            last_name = row.get('last_name', '')
            email = row.get('email', '')
            group_name = row.get('group', '')

            if not student_id:
                errors.append('student_id is required')
            if not first_name:
                errors.append('first_name is required')
            if not last_name:
                errors.append('last_name is required')
            if not email:
                errors.append('email is required')
            elif '@' not in email:
                errors.append('email is invalid')

            group = None
            if group_name:
                group = group_map.get(group_name.lower())
                if group is None:
                    errors.append(f'Group "{group_name}" not found')

            # Duplicate check within file
            if student_id in seen_ids:
                errors.append(f'Duplicate student_id in file: {student_id}')
            if email in seen_emails:
                errors.append(f'Duplicate email in file: {email}')

            if errors:
                invalid_rows.append({'row': i, 'data': row, 'errors': errors})
                continue

            # Duplicate against DB
            if student_id in existing_student_ids or email in existing_emails:
                duplicates.append({'row': i, 'data': row})
                seen_ids.add(student_id)
                seen_emails.add(email)
                continue

            seen_ids.add(student_id)
            seen_emails.add(email)

            valid_rows.append({
                'student_id': student_id,
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'group': {'id': group.id, 'name': group.name} if group else None,
                '_group_obj': group,  # internal use only, stripped from response
            })

        return valid_rows, invalid_rows, duplicates

    @transaction.atomic
    def import_rows(self, valid_rows, organization):
        """Import validated rows inside a single transaction."""
        created = []
        for row in valid_rows:
            password = secrets.token_urlsafe(12)
            user = User.objects.create_user(
                email=row['email'],
                password=password,
                first_name=row['first_name'],
                last_name=row['last_name'],
                role=Role.STUDENT,
                organization=organization,
            )
            student = Student.objects.create(
                user=user,
                organization=organization,
                student_id=row['student_id'],
                group=row.get('_group_obj'),  # use actual model instance
            )
            created.append(student)
        return created
