"""
Audit service — thin helper for creating audit log entries.

Usage:
    from apps.audit.service import audit
    from apps.audit.models import AuditAction

    audit(
        action=AuditAction.STUDENT_CREATED,
        actor=request.user,
        organization=request.user.organization,
        target_type='Student',
        target_id=str(student.id),
        metadata={'student_id': student.student_id},
        ip_address=ip,
    )

Errors are logged but never raised — audit failures must not break core operations.
"""

import logging
from .models import AuditLog, AuditAction

logger = logging.getLogger(__name__)


def audit(
    action: str,
    actor=None,
    organization=None,
    target_type: str = '',
    target_id: str = '',
    metadata: dict = None,
    ip_address: str = None,
):
    """Create an audit log entry. Silently handles errors."""
    try:
        AuditLog.objects.create(
            organization=organization,
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id else '',
            metadata=metadata or {},
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.error('Audit log creation failed: %s', exc)
