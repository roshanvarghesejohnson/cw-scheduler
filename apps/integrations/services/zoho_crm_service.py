from __future__ import annotations

import logging
import time
from typing import Optional

import requests
from django.conf import settings

from apps.bookings.models import Booking

logger = logging.getLogger(__name__)


class ZohoCRMService:
    """
    Lightweight Zoho CRM client for updating Deal assignments.
    """

    def __init__(self) -> None:
        self.base_url: str = getattr(
            settings, "ZOHO_CRM_BASE_URL", "https://www.zohoapis.in/crm/v2"
        ).rstrip("/")
        self.access_token: Optional[str] = getattr(
            settings, "ZOHO_CRM_ACCESS_TOKEN", None
        )

    def update_deal_assignment(
        self,
        crm_deal_id: Optional[str],
        technician_name: str,
        service_date,
        slot_start,
        slot_end,
        booking: Booking,
    ) -> None:
        """
        Update a Zoho CRM Deal with technician assignment details.

        Fails silently (logs errors) and never raises, so dispatch is not blocked.
        """
        if not crm_deal_id:
            return
        if not self.access_token:
            logger.warning("Zoho CRM access token not configured; skipping update")
            return

        url = f"{self.base_url}/Deals"
        service_time_str = None
        if slot_start and slot_end:
            service_time_str = f"{slot_start.strftime('%H:%M')}-{slot_end.strftime('%H:%M')}"

        closing_date = (
            service_date.strftime("%Y-%m-%d")
            if hasattr(service_date, "strftime")
            else str(service_date)
        )

        city = booking.city.name if getattr(booking, "city", None) else None
        address = getattr(booking, "address", None)
        pincode = getattr(booking, "pincode", None)
        cycle_brand = getattr(booking, "cycle_brand", None)
        cycle_model = getattr(booking, "cycle_model", None)
        service_number = getattr(booking, "id", None)

        payload = {
            "data": [
                {
                    "id": crm_deal_id,
                    "Service_Technician": technician_name,
                    "Service_Time": service_time_str,
                    "Closing_Date": closing_date,
                    "City": city,
                    "Address": address,
                    "Pin_Code": pincode,
                    "Cycle_Brand": cycle_brand,
                    "Cycle_Model": cycle_model,
                    "Service_Number": service_number,
                }
            ]
        }

        headers = {
            "Authorization": f"Zoho-oauthtoken {self.access_token}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.put(url, json=payload, headers=headers, timeout=10)
            if 200 <= resp.status_code < 300:
                logger.info(
                    "Zoho CRM updated",
                    extra={"deal_id": crm_deal_id, "technician": technician_name},
                )
            else:
                logger.warning(
                    "Zoho CRM update failed",
                    extra={
                        "deal_id": crm_deal_id,
                        "status": resp.status_code,
                        "body": resp.text[:500],
                    },
                )
        except Exception as exc:
            logger.error(
                "Zoho CRM update error",
                exc_info=exc,
                extra={"deal_id": crm_deal_id, "technician": technician_name},
            )
        finally:
            # Basic rate limiting to avoid hitting Zoho API limits during large runs.
            time.sleep(0.2)

