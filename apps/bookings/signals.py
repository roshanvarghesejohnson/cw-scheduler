from __future__ import annotations

import logging
from typing import Optional

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from apps.bookings.models import Booking
from apps.integrations.services.zoho_crm_service import (
    ZOHO_DEAL_STAGE_CUSTOMER_APPROVED,
    ZohoCRMService,
)
from apps.slots.models import Slot

logger = logging.getLogger(__name__)


def _adjust_slot_utilization(slot: Optional[Slot], delta: int) -> None:
    """
    Safely adjust slot.current_utilization by delta, enforcing bounds.
    """
    if slot is None:
        return

    original = slot.current_utilization
    new_value = original + delta

    if new_value < 0:
        new_value = 0
    if new_value > slot.max_capacity:
        new_value = slot.max_capacity

    if new_value == original:
        return

    slot.current_utilization = new_value
    slot.save(update_fields=["current_utilization"])
    logger.info(
        "Slot utilization updated: slot_id=%s new_utilization=%s",
        slot.id,
        new_value,
    )


@receiver(post_delete, sender=Booking)
def booking_post_delete_update_slot(sender, instance: Booking, **kwargs) -> None:
    """
    When a booking is deleted, decrement utilization on its slot (if any).
    """
    if instance.slot_id:
        try:
            slot = Slot.objects.get(pk=instance.slot_id)
        except Slot.DoesNotExist:
            return
        _adjust_slot_utilization(slot, delta=-1)


@receiver(pre_save, sender=Booking)
def booking_pre_save_update_slot(sender, instance: Booking, **kwargs) -> None:
    """
    When a booking's slot changes, decrement old slot and increment new slot.
    """
    if not instance.pk:
        # New booking: handled by booking creation logic elsewhere.
        return

    try:
        previous = Booking.objects.get(pk=instance.pk)
    except Booking.DoesNotExist:
        return

    old_slot_id = previous.slot_id
    new_slot_id = instance.slot_id

    if old_slot_id == new_slot_id:
        return

    old_slot: Optional[Slot] = None
    new_slot: Optional[Slot] = None

    if old_slot_id:
        try:
            old_slot = Slot.objects.get(pk=old_slot_id)
        except Slot.DoesNotExist:
            old_slot = None

    if new_slot_id:
        try:
            new_slot = Slot.objects.get(pk=new_slot_id)
        except Slot.DoesNotExist:
            new_slot = None

    if old_slot is not None:
        _adjust_slot_utilization(old_slot, delta=-1)
    if new_slot is not None:
        _adjust_slot_utilization(new_slot, delta=1)


@receiver(pre_save, sender=Booking)
def booking_pre_save_zoho_transition_cache(sender, instance: Booking, **kwargs) -> None:
    """Cache prior status/technician for post_save Zoho stage sync (admin / save() path)."""
    if not instance.pk:
        instance._zoho_prev_status = None  # type: ignore[attr-defined]
        instance._zoho_prev_technician_id = None  # type: ignore[attr-defined]
        return
    try:
        prev = Booking.objects.only("status", "technician_id").get(pk=instance.pk)
    except Booking.DoesNotExist:
        instance._zoho_prev_status = None  # type: ignore[attr-defined]
        instance._zoho_prev_technician_id = None  # type: ignore[attr-defined]
        return
    instance._zoho_prev_status = prev.status  # type: ignore[attr-defined]
    instance._zoho_prev_technician_id = prev.technician_id  # type: ignore[attr-defined]


@receiver(post_save, sender=Booking)
def booking_post_save_zoho_customer_approved_stage(sender, instance: Booking, **kwargs) -> None:
    """
    When a booking becomes CONFIRMED with a technician (non-bulk save path),
    move Zoho deal to Customer Approved. Skips if already CONFIRMED with same
    technician (no transition) to avoid duplicate CRM updates.
    """
    if kwargs.get("raw"):
        return
    if (
        instance.status != Booking.Status.CONFIRMED
        or not instance.technician_id
        or not instance.crm_deal_id
    ):
        return

    prev_status = getattr(instance, "_zoho_prev_status", None)
    prev_tech = getattr(instance, "_zoho_prev_technician_id", None)
    if (
        prev_status == Booking.Status.CONFIRMED
        and prev_tech == instance.technician_id
    ):
        return

    b = (
        Booking.objects.filter(pk=instance.pk)
        .select_related("technician", "slot", "customer", "city")
        .first()
    )
    if not b or not b.technician_id:
        return

    print(
        "Zoho (signal): confirmed+technician booking",
        b.pk,
        "deal",
        b.crm_deal_id,
        "→ stage",
        ZOHO_DEAL_STAGE_CUSTOMER_APPROVED,
    )
    try:
        crm = ZohoCRMService()
        crm.update_deal(
            b.crm_deal_id,
            {"Stage": ZOHO_DEAL_STAGE_CUSTOMER_APPROVED},
        )
        crm.update_deal_assignment(
            b.crm_deal_id,
            b.technician.name,
            b.service_date,
            b.slot.start_time if b.slot_id else None,
            b.slot.end_time if b.slot_id else None,
            b,
        )
    except Exception:
        logger.exception(
            "Zoho CRM customer-approved sync failed for booking %s", b.pk
        )
