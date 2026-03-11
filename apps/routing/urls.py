from __future__ import annotations

from django.urls import path

from apps.routing.api.dispatch_plan_view import DispatchPlanView
from apps.routing.views import DispatchDashboardView

urlpatterns = [
    path("plan/", DispatchPlanView.as_view(), name="dispatch-plan"),
    path("dashboard/", DispatchDashboardView.as_view(), name="dispatch-dashboard"),
]


