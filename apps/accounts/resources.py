"""
Base multi-tenant ModelResource for django-import-export.
"""

from import_export import resources
from apps.accounts.widgets import OrgForeignKeyWidget


class OrgScopedModelResource(resources.ModelResource):
    """
    Base ModelResource ensuring strict multi-tenant isolation.
    Restricts querysets, foreign keys, and created records to the active organization.
    """

    class Meta:
        rollback_on_validation_errors = True
        skip_unchanged = True
        report_skipped = True
        clean_model_instances = True

    def __init__(self, organization=None, is_superuser=False, **kwargs):
        super().__init__(**kwargs)
        self.organization = organization
        self.is_superuser = is_superuser
        for field in self.fields.values():
            if isinstance(field.widget, OrgForeignKeyWidget):
                field.widget.resource = self

    def get_queryset(self):
        qs = super().get_queryset()
        if self.is_superuser and self.organization is None:
            return qs
        if self.organization is not None:
            if any(f.name == 'organization' for f in self._meta.model._meta.fields):
                return qs.filter(organization=self.organization)
            elif hasattr(self, 'org_field_lookup'):
                return qs.filter(**{self.org_field_lookup: self.organization})
        return qs.none()

    def before_save_instance(self, instance, row, **kwargs):
        super().before_save_instance(instance, row, **kwargs)
        if any(f.name == 'organization' for f in instance._meta.fields):
            if self.organization is not None:
                instance.organization = self.organization

    def import_instance(self, instance, row, **kwargs):
        super().import_instance(instance, row, **kwargs)
        self.before_save_instance(instance, row, **kwargs)

    def import_data(self, dataset, dry_run=False, raise_errors=False, use_transactions=None, collect_failed_rows=False, rollback_on_validation_errors=None, **kwargs):
        if rollback_on_validation_errors is None:
            rollback_on_validation_errors = getattr(self._meta, 'rollback_on_validation_errors', False)
        return super().import_data(
            dataset,
            dry_run=dry_run,
            raise_errors=raise_errors,
            use_transactions=use_transactions,
            collect_failed_rows=collect_failed_rows,
            rollback_on_validation_errors=rollback_on_validation_errors,
            **kwargs
        )
