"""
Locations app.

An AttendanceLocation defines a physical point + radius where attendance can occur.
Distance calculation uses haversine formula on the server.
PostGIS is not required for MVP but the model is designed to accept it later.
"""

from django.db import models


class LocationStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    ARCHIVED = 'ARCHIVED', 'Archived'


class AttendanceLocation(models.Model):
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='locations',
    )
    name = models.CharField(max_length=255)

    # Stored as plain decimal fields. PostGIS can replace this later
    # without changing the data shape.
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)

    # Allowed radius in metres
    radius_meters = models.PositiveIntegerField(
        default=150,
        help_text='Radius in metres within which attendance is valid',
    )

    status = models.CharField(
        max_length=20,
        choices=LocationStatus.choices,
        default=LocationStatus.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'attendance_locations'
        indexes = [
            models.Index(fields=['organization', 'status']),
        ]

    def __str__(self):
        return f'{self.name} (r={self.radius_meters}m)'
