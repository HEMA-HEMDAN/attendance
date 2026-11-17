from rest_framework import serializers
from .models import AttendanceLocation


class AttendanceLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceLocation
        fields = ['id', 'name', 'latitude', 'longitude', 'radius_meters', 'status', 'created_at']
        read_only_fields = ['id', 'created_at']

    def create(self, validated_data):
        validated_data['organization'] = self.context['request'].user.organization
        return super().create(validated_data)
