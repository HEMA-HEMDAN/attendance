"""
Location utility functions.

Server-side distance calculation using the haversine formula.
The client provides raw coordinates — the server makes the inside/outside decision.
"""

import math


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two points on earth (in metres).
    Uses haversine formula.
    """
    R = 6_371_000  # Earth radius in metres

    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def validate_coordinates(lat: float, lon: float) -> bool:
    """Validate that coordinates are within legal ranges."""
    try:
        lat = float(lat)
        lon = float(lon)
        return -90 <= lat <= 90 and -180 <= lon <= 180
    except (TypeError, ValueError):
        return False
