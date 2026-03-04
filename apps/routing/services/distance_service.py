"""
Distance computation layer for the CycleWorks Scheduling Engine.

This module provides a reusable abstraction for computing distance between
geo points. The scheduling engine must call DistanceService, not provider
implementations directly. Future providers may use road-network travel
distance or time (e.g. Google Maps, OSRM, Mapbox) instead of straight-line
distance; assignment logic remains unchanged by swapping the provider.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple


class DistanceProvider:
    """
    Interface for distance computation between two geo points.

    Implementations may use straight-line (Haversine), road-network, or
    external APIs; the scheduling engine depends only on this interface.
    """

    def distance_km(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Return distance in kilometers between (lat1, lon1) and (lat2, lon2)."""
        raise NotImplementedError


class HaversineDistanceProvider(DistanceProvider):
    """
    Straight-line distance using the Haversine formula.

    Uses Earth radius 6371 km. Suitable for coarse filtering; future
    providers may return road-network travel distance or time.
    """

    EARTH_RADIUS_KM = 6371.0

    def distance_km(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Return great-circle distance in kilometers."""
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)

        a = (
            math.sin(dphi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return self.EARTH_RADIUS_KM * c


class DistanceService:
    """
    Facade for distance computation; delegates to a pluggable provider.

    Use this class from the scheduling engine. Do not call provider
    implementations directly so that the engine can later switch to
    road-network or API-based providers without code changes.
    """

    def __init__(self, provider: Optional[DistanceProvider] = None) -> None:
        self._provider = provider if provider is not None else HaversineDistanceProvider()

    def distance_km(
        self,
        lat1: Optional[float],
        lon1: Optional[float],
        lat2: Optional[float],
        lon2: Optional[float],
    ) -> float:
        """
        Return distance in kilometers between two points.

        If any coordinate is None, returns float("inf") so that missing
        coordinates are treated as unreachable in assignment logic.
        """
        if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
            return float("inf")
        return self._provider.distance_km(lat1, lon1, lat2, lon2)

    def batch_distance_from_point(
        self,
        origin_lat: float,
        origin_lon: float,
        destinations: List[Tuple[float, float]],
    ) -> List[float]:
        """
        Return list of distances in km from (origin_lat, origin_lon) to each
        (lat, lon) in destinations. Uses the configured provider for each pair.
        """
        return [
            self.distance_km(origin_lat, origin_lon, lat, lon)
            for lat, lon in destinations
        ]
