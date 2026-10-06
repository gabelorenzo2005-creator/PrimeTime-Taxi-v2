"""Explicit audit records in the caller's operational transaction, never credentials."""
from .models import AuditRecord


def record(actor, action, subject, details=None):
    return AuditRecord.objects.create(actor=actor, action=action,
                                      subject_type=subject._meta.label_lower,
                                      subject_id=subject.pk, details=details or {})
