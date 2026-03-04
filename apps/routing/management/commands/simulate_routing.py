"""
Simulation command to evaluate routing efficiency of the scheduling engine.

Generates synthetic geo-distributed bookings for a given city/date, runs the
full scheduling pipeline (slot + technician assignment), and reports total
travel distance per technician and city-wide. Supports multiple assignment
strategies and spatial demand distributions (uniform vs clustered) to evaluate
routing performance under both uniformly spread demand and realistic
clustered demand. Can perform repeated simulations with different seeds to
estimate expected routing efficiency under stochastic demand.
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import List, Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.bookings.models import Booking
from apps.cities.models import City
from apps.customers.models import Customer
from apps.routing.services import technician_assignment_service as tech_assignment_module
from apps.routing.services.distance_service import DistanceService
from apps.routing.services.scheduling_service import SchedulingService
from apps.routing.services.technician_assignment_service import (
    TechnicianAssignmentService,
)
from apps.slots.models import Slot

# Hardcoded bounding box center and variance for synthetic coordinates.
SIM_CENTER_LAT = 19.0
SIM_CENTER_LON = 72.0
SIM_VARIANCE = 0.05
CLUSTER_VARIANCE = SIM_VARIANCE / 4  # Tighter spread around cluster centers


class Command(BaseCommand):
    """
    Simulate geo-distributed bookings and measure total travel distance to
    evaluate routing heuristic performance. Supports multiple assignment
    strategies, demand distributions (uniform vs clustered), and repeated runs
    with different seeds to estimate expected routing efficiency under
    stochastic demand.
    """

    help = (
        "Generate synthetic bookings, run scheduling pipeline, and report "
        "travel distance metrics for routing evaluation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--city",
            required=True,
            help="Name of the city as stored in the City model.",
        )
        parser.add_argument(
            "--date",
            required=True,
            help="Service date in YYYY-MM-DD format.",
        )
        parser.add_argument(
            "--num-bookings",
            type=int,
            default=50,
            help="Number of synthetic bookings to create (default: 50).",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=None,
            help="Random seed for reproducibility.",
        )
        parser.add_argument(
            "--strategy",
            choices=["baseline", "continuity"],
            default="continuity",
            help=(
                "Assignment strategy: 'baseline' = pure distance greedy (no "
                "continuity penalty), 'continuity' = distance + continuity "
                "penalty (default)."
            ),
        )
        parser.add_argument(
            "--distribution",
            choices=["uniform", "clustered"],
            default="uniform",
            help=(
                "Spatial demand: 'uniform' = random within bounding box, "
                "'clustered' = bookings around multiple cluster centers (default: uniform)."
            ),
        )
        parser.add_argument(
            "--runs",
            type=int,
            default=1,
            help="Number of repeated simulations with different seeds (default: 1).",
        )

    def handle(self, *args, **options) -> None:
        city_name = options["city"]
        date_str = options["date"]
        num_bookings = options["num_bookings"]
        seed: Optional[int] = options["seed"]
        strategy = options["strategy"]
        distribution = options["distribution"]
        runs = options["runs"]

        if runs < 1:
            raise CommandError("--runs must be at least 1.")

        try:
            service_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError("Invalid date format. Expected YYYY-MM-DD.") from exc

        try:
            city = City.objects.get(name=city_name)
        except City.DoesNotExist as exc:
            raise CommandError(f"City with name '{city_name}' does not exist.") from exc

        if not Slot.objects.filter(city=city, date=service_date).exists():
            raise CommandError(
                f"No slots exist for city '{city_name}' on {service_date}. "
                "Create slots first (e.g. via admin)."
            )

        if num_bookings < 1:
            raise CommandError("--num-bookings must be at least 1.")

        distance_service = DistanceService()

        if runs == 1:
            run_seed = seed if seed is not None else random.getrandbits(32)
            random.seed(run_seed)
            self._run_single(
                city=city,
                service_date=service_date,
                num_bookings=num_bookings,
                strategy=strategy,
                distribution=distribution,
                distance_service=distance_service,
            )
            return

        # Multiple runs: each run in its own atomic block, then roll back.
        city_totals: List[float] = []
        seeds_used: List[int] = []
        for i in range(runs):
            run_seed = (seed + i) if seed is not None else random.getrandbits(32)
            seeds_used.append(run_seed)
            random.seed(run_seed)
            with transaction.atomic():
                self._create_and_run(
                    city=city,
                    service_date=service_date,
                    num_bookings=num_bookings,
                    strategy=strategy,
                    distribution=distribution,
                )
                city_total = self._compute_city_total(
                    city=city,
                    service_date=service_date,
                    distance_service=distance_service,
                )
                city_totals.append(city_total)
                transaction.set_rollback(True)

        self.stdout.write(f"Distribution: {distribution}")
        self.stdout.write(f"Strategy: {strategy}")
        self.stdout.write(f"Runs: {runs}")
        self.stdout.write(f"Seeds: {seeds_used[0]}..{seeds_used[-1]}" if seed is not None else f"Seeds: {seeds_used}")
        self.stdout.write("")
        avg_dist = sum(city_totals) / len(city_totals)
        self.stdout.write(
            self.style.SUCCESS(f"Average city distance: {avg_dist:.2f} km")
        )
        self.stdout.write(
            self.style.SUCCESS(f"Min city distance: {min(city_totals):.2f} km")
        )
        self.stdout.write(
            self.style.SUCCESS(f"Max city distance: {max(city_totals):.2f} km")
        )

    def _create_and_run(
        self,
        city,
        service_date,
        num_bookings: int,
        strategy: str,
        distribution: str,
    ) -> None:
        """Create synthetic data and run scheduling pipeline (slot + tech)."""
        customers = self._create_synthetic_customers(
            city=city, num_bookings=num_bookings, distribution=distribution
        )
        for i, cust in enumerate(customers):
            Booking.objects.create(
                customer=cust,
                city=city,
                service_date=service_date,
                status=Booking.Status.REQUESTED,
                slot=None,
                technician=None,
            )
        SchedulingService().auto_assign_slots(
            city=city, service_date=service_date
        )
        original = tech_assignment_module.CONTINUITY_FACTOR
        try:
            if strategy == "baseline":
                tech_assignment_module.CONTINUITY_FACTOR = 0.0
            TechnicianAssignmentService().auto_assign_technicians(
                city=city, service_date=service_date
            )
        finally:
            tech_assignment_module.CONTINUITY_FACTOR = original

    def _create_synthetic_customers(
        self, city, num_bookings: int, distribution: str
    ) -> List[Customer]:
        """Create synthetic customers; return list for booking creation."""
        customers: List[Customer] = []
        if distribution == "uniform":
            for i in range(1, num_bookings + 1):
                lat = SIM_CENTER_LAT + random.uniform(-SIM_VARIANCE, SIM_VARIANCE)
                lon = SIM_CENTER_LON + random.uniform(-SIM_VARIANCE, SIM_VARIANCE)
                cust = Customer.objects.create(
                    name=f"Sim Customer {i}",
                    phone=f"sim-{i}",
                    address="Sim",
                    city=city,
                    latitude=lat,
                    longitude=lon,
                )
                customers.append(cust)
        else:
            num_clusters = max(3, num_bookings // 15)
            cluster_centers = [
                (
                    SIM_CENTER_LAT + random.uniform(-SIM_VARIANCE, SIM_VARIANCE),
                    SIM_CENTER_LON + random.uniform(-SIM_VARIANCE, SIM_VARIANCE),
                )
                for _ in range(num_clusters)
            ]
            for i in range(1, num_bookings + 1):
                center_lat, center_lon = random.choice(cluster_centers)
                lat = center_lat + random.uniform(
                    -CLUSTER_VARIANCE, CLUSTER_VARIANCE
                )
                lon = center_lon + random.uniform(
                    -CLUSTER_VARIANCE, CLUSTER_VARIANCE
                )
                cust = Customer.objects.create(
                    name=f"Sim Customer {i}",
                    phone=f"sim-{i}",
                    address="Sim",
                    city=city,
                    latitude=lat,
                    longitude=lon,
                )
                customers.append(cust)
        return customers

    def _compute_city_total(self, city, service_date, distance_service) -> float:
        """Compute city-wide total travel distance from current DB state."""
        assigned = (
            Booking.objects.filter(
                city=city,
                service_date=service_date,
                technician__isnull=False,
                slot__isnull=False,
            )
            .select_related("technician", "customer", "slot")
            .order_by("technician_id", "slot__start_time", "created_at")
        )
        tech_totals: dict = {}
        for booking in assigned:
            tech = booking.technician
            if tech.pk not in tech_totals:
                tech_totals[tech.pk] = {"tech": tech, "bookings": []}
            tech_totals[tech.pk]["bookings"].append(booking)
        city_total = 0.0
        for data in tech_totals.values():
            tech = data["tech"]
            ordered = data["bookings"]
            base_lat, base_lon = tech.base_latitude, tech.base_longitude
            for idx, b in enumerate(ordered):
                c_lat, c_lon = b.customer.latitude, b.customer.longitude
                if idx == 0:
                    leg = distance_service.distance_km(
                        base_lat, base_lon, c_lat, c_lon
                    )
                else:
                    prev = ordered[idx - 1]
                    leg = distance_service.distance_km(
                        prev.customer.latitude,
                        prev.customer.longitude,
                        c_lat,
                        c_lon,
                    )
                if leg != float("inf"):
                    city_total += leg
        return city_total

    def _run_single(
        self,
        city,
        service_date,
        num_bookings: int,
        strategy: str,
        distribution: str,
        distance_service,
    ) -> None:
        """Single run: create data, run pipeline, report per-tech and city total."""
        with transaction.atomic():
            customers = self._create_synthetic_customers(
                city=city,
                num_bookings=num_bookings,
                distribution=distribution,
            )
            for i, cust in enumerate(customers):
                Booking.objects.create(
                    customer=cust,
                    city=city,
                    service_date=service_date,
                    status=Booking.Status.REQUESTED,
                    slot=None,
                    technician=None,
                )
            SchedulingService().auto_assign_slots(
                city=city, service_date=service_date
            )
            original = tech_assignment_module.CONTINUITY_FACTOR
            try:
                if strategy == "baseline":
                    tech_assignment_module.CONTINUITY_FACTOR = 0.0
                TechnicianAssignmentService().auto_assign_technicians(
                    city=city, service_date=service_date
                )
            finally:
                tech_assignment_module.CONTINUITY_FACTOR = original

        assigned_bookings = (
            Booking.objects.filter(
                city=city,
                service_date=service_date,
                technician__isnull=False,
                slot__isnull=False,
            )
            .select_related("technician", "customer", "slot")
            .order_by("technician_id", "slot__start_time", "created_at")
        )
        tech_totals = {}
        for booking in assigned_bookings:
            tech = booking.technician
            if tech.pk not in tech_totals:
                tech_totals[tech.pk] = {"tech": tech, "distance_km": 0.0, "bookings": []}
            tech_totals[tech.pk]["bookings"].append(booking)

        for data in tech_totals.values():
            tech = data["tech"]
            ordered = data["bookings"]
            total = 0.0
            base_lat, base_lon = tech.base_latitude, tech.base_longitude
            for idx, b in enumerate(ordered):
                c_lat, c_lon = b.customer.latitude, b.customer.longitude
                if idx == 0:
                    leg = distance_service.distance_km(
                        base_lat, base_lon, c_lat, c_lon
                    )
                else:
                    prev = ordered[idx - 1]
                    leg = distance_service.distance_km(
                        prev.customer.latitude,
                        prev.customer.longitude,
                        c_lat,
                        c_lon,
                    )
                if leg != float("inf"):
                    total += leg
            data["distance_km"] = total

        self.stdout.write(f"Distribution: {distribution}")
        self.stdout.write(f"Strategy: {strategy}")
        self.stdout.write("")
        city_total = 0.0
        for tech_pk, data in tech_totals.items():
            tech = data["tech"]
            dist = data["distance_km"]
            city_total += dist
            self.stdout.write(
                f"Tech {tech.pk} ({tech.name}): total_distance_km = {dist:.2f}"
            )
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"City total distance = {city_total:.2f} km")
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Bookings assigned = {sum(len(d['bookings']) for d in tech_totals.values())}"
            )
        )
