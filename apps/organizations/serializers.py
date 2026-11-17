from rest_framework import serializers
from .models import Organization


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['id', 'name', 'slug', 'timezone', 'status', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate_slug(self, value):
        qs = Organization.objects.filter(slug=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('An organization with this slug already exists.')
        return value

    def validate_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError('Name is required.')
        return value.strip()
