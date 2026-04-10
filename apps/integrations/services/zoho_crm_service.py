from __future__ import annotations

import logging
import time
from typing import Optional

import requests
from django.conf import settings

from apps.bookings.models import Booking

logger = logging.getLogger(__name__)

ZOHO_DEAL_STAGE = "Order Received"
ZOHO_DEAL_PIPELINE = "Cycleworks.in"
ZOHO_DEAL_STAGE_CUSTOMER_APPROVED = "Customer Approved"


class ZohoCRMService:
    """
    Zoho CRM client: OAuth refresh for access token, Deal create, Deal update.
    """

    def __init__(self) -> None:
        self.base_url: str = getattr(
            settings, "ZOHO_CRM_BASE_URL", "https://www.zohoapis.in/crm/v2"
        ).rstrip("/")
        self.access_token: Optional[str] = getattr(
            settings, "ZOHO_CRM_ACCESS_TOKEN", None
        )

    def get_access_token(self) -> str:
        """
        Exchange refresh_token for a fresh access_token (Zoho India accounts).
        """
        token_url = getattr(
            settings,
            "ZOHO_OAUTH_TOKEN_URL",
            "https://accounts.zoho.in/oauth/v2/token",
        )
        refresh_token = getattr(settings, "ZOHO_CRM_REFRESH_TOKEN", None)
        client_id = getattr(settings, "ZOHO_CLIENT_ID", None)
        client_secret = getattr(settings, "ZOHO_CLIENT_SECRET", None)

        if not refresh_token or not client_id or not client_secret:
            logger.error(
                "Zoho OAuth missing env (ZOHO_CRM_REFRESH_TOKEN, "
                "ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET)"
            )
            raise RuntimeError(
                "Zoho OAuth requires ZOHO_CRM_REFRESH_TOKEN, ZOHO_CLIENT_ID, and "
                "ZOHO_CLIENT_SECRET to be set."
            )

        resp = requests.post(
            token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        body = resp.text
        if resp.status_code != 200:
            logger.error("Zoho OAuth token refresh failed: status=%s body=%s", resp.status_code, body)
            raise RuntimeError(
                f"Zoho OAuth token refresh failed: status={resp.status_code} body={body}"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            logger.error("Zoho OAuth invalid JSON: body=%s", body)
            raise RuntimeError(
                f"Zoho OAuth token refresh: invalid JSON body={body}"
            ) from exc
        access = data.get("access_token")
        if not access:
            logger.error("Zoho OAuth response missing access_token: body=%s", body)
            raise RuntimeError(
                f"Zoho OAuth response missing access_token: body={body}"
            )
        return access

    def build_deal_payload(self, booking: Booking) -> dict:
        """
        Build Zoho CRM Deal create payload (single record). Omits keys whose
        values are empty so Zoho does not receive nulls for optional fields.
        """
        customer = booking.customer
        record: dict = {
            "Deal_Name": f"{customer.name} - {booking.service_date}",
            "Stage": ZOHO_DEAL_STAGE,
            "Pipeline": ZOHO_DEAL_PIPELINE,
        }

        phone = (customer.phone or "").strip()
        if phone:
            record["Phone"] = phone

        city = booking.city
        if city:
            record["City"] = city.name

        if hasattr(booking.service_date, "strftime"):
            record["Closing_Date"] = booking.service_date.strftime("%Y-%m-%d")
        else:
            record["Closing_Date"] = str(booking.service_date)

        service_type = booking.service_type or "basic"
        address = booking.address or customer.address
        pincode = booking.pincode or customer.pincode_temp

        if address:
            record["Address"] = address
            record["Description"] = f"{service_type} service at {address}"

        if pincode:
            record["Pin_Code"] = pincode

        return {"data": [record]}

    def create_deal(self, booking: Booking) -> str:
        """
        Create a Zoho CRM Deal (minimal payload). Refreshes access token first.

        Raises on any failure so callers and logs surface errors.
        """
        self.access_token = self.get_access_token()

        url = f"{self.base_url}/Deals"
        headers = {
            "Authorization": f"Zoho-oauthtoken {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = self.build_deal_payload(booking)

        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        body = resp.text

        if not (200 <= resp.status_code < 300):
            logger.error("Zoho create deal failed: status=%s body=%s", resp.status_code, body)
            raise RuntimeError(
                f"Zoho create deal failed: status={resp.status_code} body={body}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            logger.error("Zoho create deal invalid JSON: body=%s", body)
            raise RuntimeError(
                f"Zoho create deal: invalid JSON body={body}"
            ) from exc
        try:
            deal_id = data["data"][0]["details"]["id"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.error("Zoho create deal could not parse deal id: body=%s", body)
            raise RuntimeError(
                f"Zoho create deal: could not parse deal id from response: {body}"
            ) from exc

        return str(deal_id)

    def update_deal(self, deal_id: str, fields: dict) -> None:
        """
        Generic CRM Deal update by record id (PUT /Deals/{deal_id}).
        Refreshes OAuth token before the request.
        """
        self.access_token = self.get_access_token()
        url = f"{self.base_url}/Deals/{deal_id}"
        record = dict(fields)
        if "id" not in record:
            record["id"] = deal_id
        payload = {"data": [record]}
        headers = {
            "Authorization": f"Zoho-oauthtoken {self.access_token}",
            "Content-Type": "application/json",
        }
        resp = requests.put(url, json=payload, headers=headers, timeout=30)
        if not (200 <= resp.status_code < 300):
            logger.error(
                "Zoho update deal failed: deal_id=%s status=%s body=%s",
                deal_id,
                resp.status_code,
                resp.text,
            )
            raise RuntimeError(
                f"Zoho update deal failed: status={resp.status_code} body={resp.text}"
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
        try:
            self.access_token = self.get_access_token()
        except Exception as exc:
            logger.warning("Zoho token refresh failed; skipping deal update: %s", exc)
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

        customer = booking.customer
        city = booking.city.name if booking.city else None
        address = booking.address or customer.address
        pincode = booking.pincode or customer.pincode_temp

        row = {
            "id": crm_deal_id,
            "Service_Technician": technician_name,
            "Service_Time": service_time_str,
            "Closing_Date": closing_date,
            "City": city,
            "Cycle_Brand": customer.cycle_brand,
            "Cycle_Model": customer.cycle_model,
            "Service_Number": booking.id,
        }
        if address:
            row["Address"] = address
        if pincode:
            row["Pin_Code"] = pincode

        payload = {"data": [row]}

        headers = {
            "Authorization": f"Zoho-oauthtoken {self.access_token}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.put(url, json=payload, headers=headers, timeout=10)
            if not (200 <= resp.status_code < 300):
                logger.warning(
                    "Zoho CRM update failed: status=%s body=%s",
                    resp.status_code,
                    resp.text,
                )
        except Exception as exc:
            logger.warning("Zoho CRM update failed: %s", exc)
        finally:
            time.sleep(0.2)
