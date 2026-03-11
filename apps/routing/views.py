from django.views.generic import TemplateView


class DispatchDashboardView(TemplateView):
    """
    Simple internal dashboard page to visualize dispatch plans.

    Uses the /api/dispatch/plan/ endpoint via JavaScript to fetch data and
    render technician routes and metrics. Read-only; does not modify data.
    """

    template_name = "dispatch_dashboard.html"

