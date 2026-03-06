"""
Geocoding service for the CycleWorks Scheduling Engine.

Uses OpenStreetMap Nominatim API to convert addresses to coordinates.
Returns (latitude, longitude) or None if geocoding fails.
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "CycleWorks-Scheduler/1.0 (contact@cycleworks.in)"


class GeocodingService:
    """
    Geocode addresses using OpenStreetMap Nominatim.

    Returns (latitude, longitude) or None on failure.
    Respects Nominatim usage policy (1 req/sec, User-Agent required).
    """

    def geocode_address(
        self, address: str, city: Optional[str] = None
    ) -> Optional[Tuple[float, float]]:
        """
        Geocode an address to (latitude, longitude).

        Args:
            address: Full address or street address.
            city: Optional city name to improve accuracy (appended to query).

        Returns:
            (latitude, longitude) tuple if successful, None otherwise.
        """
        if not address or not address.strip():
            return None

        query = address.strip()
        if city and city.strip():
            query = f"{query}, {city.strip()}"

        params = {
            "q": query,
            "format": "json",
            "limit": 1,
        }
        headers = {"User-Agent": USER_AGENT}

        try:
            response = requests.get(
                NOMINATIM_URL,
                params=params,
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if not data:
                logger.warning("Geocoding returned no results for: %s", query[:80])
                return None
            lat = float(data[0]["lat"])
            lon = float(data[0]["lon"])
            return (lat, lon)
        except (requests.RequestException, KeyError, ValueError, IndexError) as e:
            logger.warning("Geocoding failed for '%s': %s", query[:80], e)
            return None
        finally:
            time.sleep(1)  # Nominatim usage policy: max 1 request per second
