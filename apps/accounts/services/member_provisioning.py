import logging
import secrets
from django.conf import settings
from django.core.mail import send_mail
from django.core.exceptions import ValidationError
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from apps.accounts.models import User, Role

logger = logging.getLogger(__name__)


class MemberProvisioningService:
    @staticmethod
    def get_or_create_member_user(organization, email, first_name, last_name, role, password=None):
        """
        Safely gets or creates a User for a member profile within the organization.
        Enforces tenant isolation, role match, and creates users with high-entropy usable password hashes.
        Returns tuple: (user, is_new)
        """
        normalized_email = email.strip().lower()
        existing_user = User.objects.filter(email=normalized_email).first()

        if existing_user:
            if existing_user.organization_id != getattr(organization, 'id', organization):
                raise ValidationError(f"Email '{normalized_email}' is already registered to another organization.")
            if existing_user.role != role:
                raise ValidationError(f"User '{normalized_email}' has role '{existing_user.role}', expected '{role}'.")
            return existing_user, False

        # Create new user with explicit password or cryptographically secure random password hash
        raw_password = password or secrets.token_urlsafe(32)
        user = User.objects.create_user(
            email=normalized_email,
            password=raw_password,
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            role=role,
            organization=organization,
            is_active=True,
        )
        return user, True

    @staticmethod
    def send_activation_email(user_id):
        """
        Generates a standard Django password-reset/activation token and sends the activation email.
        Safe against email delivery failures: logs error without rolling back already-committed records.
        """
        user = User.objects.filter(pk=user_id, is_active=True).first()
        if not user or not user.email:
            return

        try:
            token = default_token_generator.make_token(user)
            uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
            frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000').rstrip('/')
            activation_url = f"{frontend_url}/reset-password/{uidb64}/{token}/"

            subject = "Welcome to Bio Attendance — Activate Your Account"
            message = (
                f"Hello {user.get_full_name()},\n\n"
                f"Your account for {user.organization.name if user.organization else 'Bio Attendance'} has been provisioned.\n\n"
                f"Please click the link below to set your account password and get started:\n"
                f"{activation_url}\n\n"
                f"This activation link will expire in 48 hours.\n\n"
                f"Best regards,\nBio Attendance Team"
            )

            send_mail(
                subject=subject,
                message=message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@bioattendance.edu'),
                recipient_list=[user.email],
                fail_silently=False,
            )
            logger.info("Dispatched activation email to user %s (%s)", user.id, user.email)
        except Exception as err:
            logger.error("Failed to send activation email to user %s: %s", user_id, err)
