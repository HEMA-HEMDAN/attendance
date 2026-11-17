import pytest
from django.core import mail
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from rest_framework.test import APIClient
from apps.accounts.models import User, Role
from apps.organizations.models import Organization
from apps.accounts.services.member_provisioning import MemberProvisioningService
from apps.staff.serializers import DoctorSerializer, TeachingAssistantSerializer


@pytest.mark.django_db
class TestMemberProvisioningAndActivation:
    @pytest.fixture
    def setup_data(self):
        org = Organization.objects.create(name='Alpha University', slug='alpha-uni')
        org2 = Organization.objects.create(name='Beta University', slug='beta-uni')
        return {'org': org, 'org2': org2}

    def test_provisioning_creates_usable_random_password_hash(self, setup_data):
        org = setup_data['org']
        user, is_new = MemberProvisioningService.get_or_create_member_user(
            organization=org,
            email='new.student@alpha.edu',
            first_name='New',
            last_name='Student',
            role=Role.STUDENT
        )
        assert is_new is True
        assert user.has_usable_password() is True
        # Verify it's not any predictable password
        assert not user.check_password('Password123!')
        assert not user.check_password('new.student@alpha.edu')
        assert not user.check_password('')

    def test_provisioning_cross_tenant_email_collision_rejected(self, setup_data):
        org = setup_data['org']
        org2 = setup_data['org2']
        MemberProvisioningService.get_or_create_member_user(
            organization=org,
            email='shared@univ.edu',
            first_name='Alpha',
            last_name='User',
            role=Role.STUDENT
        )
        from django.core.exceptions import ValidationError
        with pytest.raises(ValidationError, match="already registered to another organization"):
            MemberProvisioningService.get_or_create_member_user(
                organization=org2,
                email='shared@univ.edu',
                first_name='Beta',
                last_name='User',
                role=Role.STUDENT
            )

    def test_send_activation_email_dispatches_message(self, setup_data):
        org = setup_data['org']
        user, _ = MemberProvisioningService.get_or_create_member_user(
            organization=org,
            email='activate.me@alpha.edu',
            first_name='Activate',
            last_name='Me',
            role=Role.DOCTOR
        )
        mail.outbox.clear()
        MemberProvisioningService.send_activation_email(user.id)
        assert len(mail.outbox) == 1
        sent = mail.outbox[0]
        assert 'Activate Your Account' in sent.subject
        assert user.email in sent.to
        assert 'reset-password' in sent.body

    def test_end_to_end_password_reset_and_login_flow(self, setup_data):
        org = setup_data['org']
        user, _ = MemberProvisioningService.get_or_create_member_user(
            organization=org,
            email='student.reset@alpha.edu',
            first_name='Reset',
            last_name='Test',
            role=Role.STUDENT
        )
        client = APIClient()

        # Step 1: Request reset
        mail.outbox.clear()
        res_req = client.post('/api/v1/auth/password-reset/request/', {'email': 'student.reset@alpha.edu'})
        assert res_req.status_code == 200
        assert len(mail.outbox) == 1

        # Step 2: Extract token and uidb64
        token = default_token_generator.make_token(user)
        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))

        # Step 3: Confirm new password
        new_pw = 'MyNewSecurePass2026!'
        res_conf = client.post('/api/v1/auth/password-reset/confirm/', {
            'uidb64': uidb64,
            'token': token,
            'new_password': new_pw
        })
        assert res_conf.status_code == 200

        # Step 4: Login with new password
        res_login = client.post('/api/v1/auth/login/', {
            'email': 'student.reset@alpha.edu',
            'password': new_pw
        })
        assert res_login.status_code == 200
        assert 'access' in res_login.data
        assert 'refresh' in res_login.data

    @pytest.mark.django_db(transaction=True)
    def test_staff_serializers_use_random_passwords_and_send_email(self, setup_data):
        org = setup_data['org']
        admin_user = User.objects.create_user(
            email='admin@alpha.edu',
            password='AdminPass123!',
            first_name='Admin',
            last_name='One',
            role=Role.ADMIN,
            organization=org
        )

        class DummyRequest:
            user = admin_user

        mail.outbox.clear()
        doc_serializer = DoctorSerializer(
            data={
                'email': 'dr.smith@alpha.edu',
                'first_name': 'Dr',
                'last_name': 'Smith',
                'title': 'Prof.',
                'department': 'CS'
            },
            context={'request': DummyRequest()}
        )
        assert doc_serializer.is_valid(), doc_serializer.errors
        doctor = doc_serializer.save()

        assert doctor.user.has_usable_password() is True
        assert not doctor.user.check_password('Password123!')
        assert len(mail.outbox) == 1
        assert doctor.user.email in mail.outbox[0].to

    def test_student_resource_import_sets_formula_password(self, setup_data):
        import tablib
        from apps.students.resources import StudentResource
        from apps.students.models import Student

        org = setup_data['org']
        resource = StudentResource()
        resource.organization = org

        headers = ['student_id', 'email', 'first_name', 'last_name', 'department', 'academic_level', 'status']
        data = [
            ['26150009', '26150009@alpha.edu', 'Karim', 'Shawky', 'AI', '1st Year', 'ACTIVE'],
        ]
        dataset = tablib.Dataset(*data, headers=headers)
        result = resource.import_data(dataset, dry_run=False, use_transactions=True)
        assert not result.has_errors()
        assert not result.has_validation_errors()

        student = Student.objects.get(student_id='26150009', organization=org)
        user = student.user
        assert user.check_password(f"26150009#{org.slug}!") is True

    def test_student_admin_form_sets_formula_password(self, setup_data):
        from apps.students.forms import StudentAdminForm
        from apps.students.models import Student

        org = setup_data['org']
        form = StudentAdminForm(data={
            'organization': org.id,
            'student_id': '25140203',
            'email': '25140203@alpha.edu',
            'first_name': 'Mohamed',
            'last_name': 'Mostafa',
            'status': 'ACTIVE',
        })
        assert form.is_valid(), form.errors
        student = form.save()

        student.refresh_from_db()
        user = student.user
        assert user.check_password(f"25140203#{org.slug}!") is True

