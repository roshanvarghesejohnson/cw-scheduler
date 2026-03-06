# CycleWorks Scheduling System — Technical Summary

**Purpose:** Structured analysis of technician assignment, routing, and dispatch logic across the codebase to ensure no context gap before implementing or extending the technician assignment engine.

**Scope:** `apps/routing`, `apps/technicians`, `apps/bookings`, `apps/slots`, `apps/scheduling`, `apps/cities`, `apps/common`.

---

## SECTION 1 — Booking Flow

### Current flow: frontend request → database write

1. **Frontend** (e.g. Zoho Sites) sends a **POST** to `/api/bookings/create/` with customer details and a chosen `slot_id`.
2. **Booking creation endpoint:** `apps/bookings/api/booking_create_view.py` — `BookingCreateView.post()`.
3. **Validation:** Required fields `slot_id`, `phone`, `address`; optional `name`/`customer_name`, `city`, `service_date`, `bike_type`, `email`, etc. Slot is resolved by `slot_id`; city and `service_date` are taken from the slot. If `service_date` or `city` are provided, they must match the slot.
4. **Slot capacity check:** Before creating the booking, the view computes `remaining = slot.max_capacity - slot.current_utilization`. If `remaining <= 0`, it returns `400` with message `"Selected slot is fully booked"`.
5. **Customer resolution:** Customer is looked up by `(phone, city)`; if missing, a new `Customer` is created with the provided fields.
6. **Database write (atomic transaction):**
   - `Booking` is created with `customer`, `city`, `slot`, `service_date`, `status=REQUESTED`, `technician=None`.
   - `slot.current_utilization` is incremented by 1 and saved.
   - `SchedulingService().auto_assign_slots(city, service_date)` is called (assigns any other REQUESTED, slot-less bookings to slots).
   - `TechnicianAssignmentService().auto_assign_technicians(city, service_date)` is called (assigns technicians to slot-assigned, technician-less bookings).
   - Booking is refreshed from DB.
7. **Response:** `201` with `success`, `message`, `booking_id`, `status`, `slot_id`.

### Where booking records are stored

- **Model:** `apps/bookings/models.py` — `Booking`.
- **Table:** Django-managed; table name follows app label (e.g. `bookings_booking`).

### Booking model fields related to assignment

| Field         | Purpose                                                                 |
|---------------|-------------------------------------------------------------------------|
| `slot`        | FK to `slots.Slot` (nullable). Tentative 2-hour window; set at creation or by slot assignment. |
| `technician`  | FK to `technicians.Technician` (nullable). Set by technician assignment; null until assigned. |
| `status`      | Workflow state; REQUESTED → CONFIRMED when technician is assigned.      |
| `city`        | Operational city; used for scheduling scope.                           |
| `service_date`| Target date; used for slot/technician assignment scope.                |

No separate “route” or “route_order” field exists; ordering is implied by slot and assignment order.

---

## SECTION 2 — Slot System

### Slot model (`apps/slots/models.py`)

| Field                 | Type        | Purpose |
|-----------------------|------------|---------|
| `date`                | DateField  | Calendar date of the slot. |
| `start_time`          | TimeField  | Start of 2-hour window. |
| `end_time`            | TimeField  | End of 2-hour window. |
| `city`                | FK → City  | City for this slot. |
| `max_capacity`        | PositiveIntegerField | Max bookings per slot (now = technician count). |
| `current_utilization` | PositiveIntegerField | Count of bookings assigned to this slot (cache). |

**Unique constraint:** `(date, start_time, end_time, city)`.

### How capacity works

- **max_capacity:** Set at slot creation; from slot generation it equals the number of active+available technicians in the city (one job per technician per window).
- **current_utilization:** Incremented when a booking is created with this slot (booking create view) and when `SchedulingService.auto_assign_slots` assigns bookings to this slot. Should not be edited manually; maintained by scheduling services.
- **Remaining capacity:** `max_capacity - current_utilization`. Used by slot availability and by booking create to reject fully booked slots.

### API endpoint for available slots

- **URL:** `GET /api/slots/available/`
- **View:** `apps/routing/api/slot_availability_view.py` — `SlotAvailabilityView`.
- **Query params:** `city` (required), `date` (YYYY-MM-DD, required).
- **Behavior:** Resolves city by name, calls `SlotAvailabilityService.get_available_slots(city, service_date)`, returns slots with `remaining_capacity > 0` as JSON: `slot_id`, `start_time`, `end_time` (ISO time strings), `remaining_capacity`.
- **Service:** `apps/routing/services/slot_availability_service.py` — read-only filter on `Slot` by city/date, ordered by `start_time`; only includes slots with remaining capacity.

### Slot generation system

- **Service:** `apps/scheduling/services/slot_generation_service.py`.
  - **`generate_slots_for_next_7_days()`:** “Today” is computed in `Asia/Kolkata`; generates slots for days 1–7 from today for all active cities.
  - **`generate_slots_for_city(city, dates)`:** For each city, counts active+available technicians; if 0, skips. `capacity_per_slot = tech_count`. For each date in `dates` and each window in `SLOT_WINDOWS` (9–11, 11–13, 13–15, 15–17), creates a `Slot` if no slot exists for that (city, date, start_time). Uses `bulk_create`; does not touch bookings or assignment.
- **Windows:** Four 2-hour windows: (9:00–11:00), (11:00–13:00), (13:00–15:00), (15:00–17:00).

### Management command for slot generation

- **Command:** `generate_slots` — `apps/scheduling/management/commands/generate_slots.py`.
- **Action:** Calls `generate_slots_for_next_7_days()`, prints summary (cities processed, slots created).
- **Intended use:** Run daily (e.g. cron or Render scheduled job at 20:00); no built-in cron in codebase.

---

## SECTION 3 — Technician Model

**Location:** `apps/technicians/models.py` — `Technician`.

### Fields

| Field             | Type        | Purpose |
|-------------------|------------|---------|
| `name`            | CharField  | Display/identifier. |
| `technician_type` | CharField  | INTERNAL / AGENCY. |
| `city`            | FK → City  | Primary operating city. |
| `base_location`   | TextField  | Free-text starting point (e.g. depot). |
| `is_available`    | BooleanField | Currently available for scheduling (default True). |
| `is_active`       | BooleanField | Inactive excluded from scheduling (default True). |
| `daily_capacity`  | PositiveIntegerField | Max jobs per day (default 4). |
| `base_latitude`   | FloatField (nullable) | Base/home latitude for routing. |
| `base_longitude`  | FloatField (nullable) | Base/home longitude for routing. |

### Relationships and usage

- **City:** One city per technician; assignment and slot generation filter by city.
- **Availability:** Slot generation uses `is_active=True, is_available=True`; technician assignment uses the same filter.
- **Location:** `base_latitude` / `base_longitude` are the starting point for distance and assignment. “Current” location during assignment is updated in memory only (not stored on the model) after each assignment to the last customer location.
- **Workload:** No stored “current workload” field; daily load is computed per run as count of bookings per technician for the given `service_date`. `daily_capacity` caps how many jobs a technician can be assigned in that date.

---

## SECTION 4 — Assignment Logic (Existing)

Technician assignment logic **exists** and is **automatic** when the pipeline runs.

### Where it lives

- **Service:** `apps/routing/services/technician_assignment_service.py` — `TechnicianAssignmentService.auto_assign_technicians(city, service_date)`.
- **Used by:** Booking create view (after creating a booking), `run_daily_scheduling` command, `auto_assign_technicians` command, Booking admin action “Run scheduling engine for selected bookings”, and `simulate_routing` command.

### Assignment fields on Booking

- **`technician`:** FK to `Technician`; set by assignment; null until assigned.
- **`status`:** Set to `CONFIRMED` when a technician is assigned (assignment service does this).

### Automatic vs manual

- **Automatic:** When the pipeline runs (booking create or daily scheduling), all eligible bookings (REQUESTED, has slot, no technician) for that city/date are assigned in one go via the service. No manual “assign technician” UI; admin can trigger the pipeline for selected bookings’ city/date.
- **Manual:** Technicians can be changed in Django Admin (FK editable); there is no dedicated “manual assign” action, only the bulk “Run scheduling engine” action.

### Algorithm summary

- **Input:** City and service_date.
- **Eligible bookings:** REQUESTED, has slot, technician null; ordered by slot start_time, created_at.
- **Eligible technicians:** Same city, is_active, is_available; constrained by daily capacity and per-slot exclusivity (one technician per slot).
- **Per-slot greedy global matching:** For each slot (by start_time), repeatedly pick the (technician, booking) pair that minimizes `distance_cost + continuity_penalty`, assign that pair, then update tech’s in-memory “current location” to the customer and remove both from the slot pool. Continue until no valid pairs or no finite cost.
- **Distance:** From tech’s current location (base or last assigned customer) to customer lat/lon via `DistanceService`.
- **Continuity penalty:** `CONTINUITY_FACTOR * distance_cost` (default 0.15) when the technician already has at least one assignment that day, to favor continuity.
- **Persistence:** Bulk update assigned bookings with `technician` and `status=CONFIRMED`.

---

## SECTION 5 — Routing / Distance Logic

### Distance layer

- **Location:** `apps/routing/services/distance_service.py`.
- **`DistanceProvider`:** Interface with `distance_km(lat1, lon1, lat2, lon2)`.
- **`HaversineDistanceProvider`:** Great-circle distance (Earth radius 6371 km); no external API.
- **`DistanceService`:** Facade that takes an optional provider (default Haversine). `distance_km()` returns `float('inf')` if any coordinate is None (missing coordinates treated as unreachable). Also provides `batch_distance_from_point(origin_lat, origin_lon, destinations)`.
- **Usage:** Only Haversine is used in the codebase; no Google Maps, OSRM, or Mapbox. Assignment logic uses `DistanceService` so the provider can be swapped later.

### Route optimization

- **No TSP or full route optimization.** Technician assignment uses a **per-slot greedy global matching** heuristic to minimize total cost (distance + continuity) across the slot. Order of jobs within a technician’s day is determined by assignment order (slot order + matching order), not by an explicit route-optimization step.
- **Comment in code:** “Future improvement: full route optimization per technician (e.g. TSP); current logic approximates minimizing total city-wide travel.”

### Clustering / scheduling algorithms

- **Slot assignment:** `SchedulingService.auto_assign_slots` fills slots in chronological order (start_time), FIFO by booking created_at; no geo clustering.
- **Technician assignment:** Per-slot global matching (min cost pair repeatedly); no explicit clustering. `simulate_routing` supports “clustered” vs “uniform” **synthetic** demand only for simulation, not for real assignment logic.

---

## SECTION 6 — Automation / Scheduled Jobs

No Celery, Django-cron, or in-process scheduler. Automation is via **management commands** intended for cron or manual use.

| Command               | App        | Purpose |
|-----------------------|-----------|---------|
| `generate_slots`      | scheduling | Generate slots for next 7 days for all active cities; capacity = tech count per city. Intended for daily (e.g. 20:00) cron. |
| `auto_assign_slots`   | routing   | Assign REQUESTED bookings without slot to slots for given city/date. |
| `auto_assign_technicians` | routing | Assign technicians to slot-assigned, technician-less bookings for given city/date. |
| `run_daily_scheduling`| routing   | Runs both slot and technician assignment for one city/date. Daily entrypoint for ops. |
| `simulate_routing`    | routing   | Creates synthetic bookings, runs full pipeline, reports per-tech and city-wide travel distance; supports strategies (baseline/continuity) and distributions (uniform/clustered), optional multiple runs. |

**Startup:** `apps/common/startup.py` — `ensure_default_superuser()` (ensure one superuser, log DB engine). Invoked from `scheduler_core/wsgi.py`. No scheduling or assignment runs on startup.

**Cron:** Not defined in the repo; comments suggest running `generate_slots` daily (e.g. 20:00) and `run_daily_scheduling` per city/date as needed.

---

## SECTION 7 — Current System Architecture

### Pipeline (step-by-step)

1. **Customer booking request**  
   Frontend POST to `/api/bookings/create/` with slot_id and customer details.

2. **Validation and capacity check**  
   Slot resolved; `remaining = max_capacity - current_utilization`; if ≤ 0, return 400.

3. **Customer get-or-create**  
   By (phone, city).

4. **Booking creation and slot utilization update**  
   In one transaction: create Booking (slot set, technician null, status REQUESTED); increment `slot.current_utilization`; save slot.

5. **Slot assignment**  
   `SchedulingService.auto_assign_slots(city, service_date)` assigns other REQUESTED, slot-less bookings to slots (chronological slots, FIFO bookings, capacity enforced).

6. **Technician assignment**  
   `TechnicianAssignmentService.auto_assign_technicians(city, service_date)` assigns technicians to slot-assigned, technician-less bookings (per-slot greedy global matching, distance + continuity, per-slot exclusivity, daily capacity).

7. **Response**  
   Refresh booking; return 201 with booking_id, status, slot_id.

**Where the pipeline ends:** After technician assignment and HTTP response. No follow-up “dispatch” step, no next-day batch job, no route export or driver app integration.

### Slot availability (parallel path)

- Frontend calls `GET /api/slots/available/?city=...&date=...` → `SlotAvailabilityService.get_available_slots()` → slots with `remaining_capacity > 0` returned. No assignment or booking write.

### Slot generation (separate, daily)

- `generate_slots` (or direct call to `generate_slots_for_next_7_days()`) creates/extends slots for the next 7 days per city; does not run assignment or touch existing bookings.

---

## SECTION 8 — Missing Components

From the codebase, the following are **not** present or are only partially present for a “full” technician dispatch system:

1. **Technician assignment engine**  
   **Present.** Implemented in `TechnicianAssignmentService` with distance-based, per-slot global matching and continuity. Not missing; can be extended (e.g. different strategies, constraints).

2. **Route optimization engine**  
   **Missing.** No TSP or explicit route ordering; only assignment-order and slot order. No “route” entity or sequence number. Would be needed for true route optimization and driver run sheets.

3. **Distance calculation**  
   **Present.** Haversine in `DistanceService`; pluggable for future road-network/API. Missing: actual integration with Google/OSRM/Mapbox if road distance or time is required.

4. **Next-day dispatch automation**  
   **Missing.** No job that, at a fixed time (e.g. evening before), runs slot + technician assignment for “tomorrow” for all cities. Ops must run `run_daily_scheduling` per city/date or use admin action. A single “run scheduling for tomorrow for all cities” command or cron is not implemented.

5. **Slot generation + scheduling linkage**  
   **Partial.** Slot generation runs independently (e.g. daily cron). No automatic trigger of `run_daily_scheduling` after slot generation, and no “ensure slots exist then run assignment” single entrypoint.

6. **Route/run export**  
   **Missing.** No API or export (PDF/CSV) of per-technician route or daily run sheet.

7. **Dispatch UI / driver app**  
   **Missing.** Only Django Admin; no dedicated dispatch dashboard or mobile app integration.

8. **Handling type (DIRECT/AGENCY/HYBRID)**  
   **Not used in assignment.** City has `handling_type`; assignment does not filter or route by it (e.g. no “forward to agency” or hybrid split in the engine).

---

## SECTION 9 — Safety Check: Slot Generation vs Assignment

**Conclusion: slot generation does not interfere with assignment logic.**

- **Slot generation** (`apps/scheduling/services/slot_generation_service.py`):
  - Only creates new `Slot` rows for (city, date, start_time) that do not already exist.
  - Does not read or update `Booking`, `Technician`, or any assignment state.
  - Sets `max_capacity` and `current_utilization=0` for new slots only.

- **Assignment logic** (`SchedulingService`, `TechnicianAssignmentService`):
  - Reads/writes Bookings and Slots (utilization, slot FK, technician FK, status).
  - Does not create or delete slots; only assigns bookings to existing slots and technicians.

- **Interaction:** New slots created by slot generation simply add more capacity for future bookings and for future runs of slot/technician assignment. Existing bookings and assignments are untouched. No shared mutable state between slot generation and assignment beyond the Slot table (and generation only inserts new rows). Safe to run slot generation on a schedule and assignment on the same or different schedule.

---

*End of report.*
