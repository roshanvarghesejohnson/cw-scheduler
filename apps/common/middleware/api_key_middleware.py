"""
Lightweight API key protection for public booking endpoints.

Enforces a static X-API-KEY header for requests to /api/ until full
OAuth/Zoho authentication is implemented.
"""

import logging

from django.conf import settings
from django.http import JsonResponse


logger = logging.getLogger(__name__)


class ApiKeyMiddleware:
    """
    Require X-API-KEY header to match settings.SCHEDULER_API_KEY for /api/ paths.

    If the header is missing or incorrect, returns 403 JSON. Non-API paths
    are not checked.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Allow OPTIONS requests to pass through
        if request.method == "OPTIONS":
            return self.get_response(request)

        path = request.path or ""

        # Public, unauthenticated API endpoints.
        if path.startswith("/api/slots/available/") or path.startswith(
            "/api/bookings/create/"
        ):
            return self.get_response(request)

        # Internal dispatch APIs are read-only and used by internal dashboards;
        # they do not require an API key.
        if path.startswith("/api/dispatch/"):
            return self.get_response(request)

        if path.startswith("/api/"):
            api_key = request.headers.get("X-API-KEY") or request.META.get(
                "HTTP_X_API_KEY"
            )
            expected = getattr(settings, "SCHEDULER_API_KEY", None)
            logger.debug(
                "API key check | path=%s api_key_present=%s",
                path,
                bool(api_key),
            )
            if not expected or not api_key or api_key != expected:
                logger.warning(
                    "API key rejected | path=%s header=%r", path, api_key
                )
                return JsonResponse(
                    {"detail": "Invalid or missing API key"},
                    status=403,
                )

        return self.get_response(request)
