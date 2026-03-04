"""
Lightweight API key protection for public booking endpoints.

Enforces a static X-API-KEY header for requests to /api/ until full
OAuth/Zoho authentication is implemented.
"""

from django.conf import settings
from django.http import JsonResponse


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
        if request.path.startswith("/api/"):
            api_key = request.headers.get("X-API-KEY") or request.META.get(
                "HTTP_X_API_KEY"
            )
            expected = getattr(settings, "SCHEDULER_API_KEY", None)
            if not expected or not api_key or api_key != expected:
                return JsonResponse(
                    {"detail": "Invalid or missing API key"},
                    status=403,
                )
        return self.get_response(request)
