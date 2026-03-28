from __future__ import annotations

import time
from typing import Optional

import requests
from django.conf import settings

from apps.bookings.models import Booking

ZOHO_DEAL_STAGE = "Order Received"
ZOHO_DEAL_PIPELINE = "Cycleworks.in"


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
            print(
                "ZOHO ERROR: missing OAuth env (ZOHO_CRM_REFRESH_TOKEN, "
                "ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET)"
            )
            raise RuntimeError(
                "Zoho OAuth requires ZOHO_CRM_REFRESH_TOKEN, ZOHO_CLIENT_ID, and "
                "ZOHO_CLIENT_SECRET to be set."
            )

        print("Zoho OAuth: requesting access token from", token_url)
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
        print("Zoho OAuth Status Code:", resp.status_code)
        print("Zoho OAuth Response:", body)
        if resp.status_code != 200:
            print("ZOHO ERROR:", body)
            raise RuntimeError(
                f"Zoho OAuth token refresh failed: status={resp.status_code} body={body}"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            print("ZOHO ERROR:", body)
            raise RuntimeError(
                f"Zoho OAuth token refresh: invalid JSON body={body}"
            ) from exc
        access = data.get("access_token")
        if not access:
            print("ZOHO ERROR:", body)
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

        city = getattr(booking, "city", None)
        city_name = city.name if city else None
        if city_name:
            record["City"] = city_name

        if hasattr(booking.service_date, "strftime"):
            record["Closing_Date"] = booking.service_date.strftime("%Y-%m-%d")
        else:
            record["Closing_Date"] = str(booking.service_date)

        address = (customer.address or "").strip()
        brand = (customer.cycle_brand or "").strip()
        model = (customer.cycle_model or "").strip()
        service_bits = [p for p in (brand, model) if p]
        service_type = " / ".join(service_bits) if service_bits else "Cycle service"
        if address:
            record["Description"] = f"{service_type} at {address}"
            record["Address"] = address
        else:
            record["Description"] = service_type

        amount = getattr(booking, "amount", None)
        if amount is not None:
            record["Amount"] = amount

        return {"data": [record]}

    def create_deal(self, booking: Booking) -> str:
        """
        Create a Zoho CRM Deal (minimal payload). Refreshes access token first.

        Raises on any failure so callers and logs surface errors.
        """
        print(">>> ZOHO CREATE DEAL FUNCTION TRIGGERED <<<")
        print("=== ZOHO CREATE DEAL START ===")
        self.access_token = self.get_access_token()
        print("Zoho access token in use:", self.access_token)

        url = f"{self.base_url}/Deals"
        headers = {
            "Authorization": f"Zoho-oauthtoken {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = self.build_deal_payload(booking)
        print("Zoho create deal request URL:", url)
        print("Payload:", payload)

        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        body = resp.text
        print("Status Code:", resp.status_code)
        print("Response:", body)

        # Zoho may return 200 or 201 on successful insert
        if not (200 <= resp.status_code < 300):
            print("ZOHO ERROR:", resp.text)
            raise RuntimeError(
                f"Zoho create deal failed: status={resp.status_code} body={body}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            print("ZOHO ERROR:", body)
            raise RuntimeError(
                f"Zoho create deal: invalid JSON body={body}"
            ) from exc
        try:
            deal_id = data["data"][0]["details"]["id"]
        except (KeyError, IndexError, TypeError) as exc:
            print("ZOHO ERROR:", body)
            raise RuntimeError(
                f"Zoho create deal: could not parse deal id from response: {body}"
            ) from exc

        print("Deal Created Successfully:", deal_id)
        return str(deal_id)

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
            print("ZOHO ERROR (token refresh; skipping deal update):", exc)
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
            print("Zoho CRM update Status Code:", resp.status_code)
            print("Zoho CRM update Response:", resp.text)
            if 200 <= resp.status_code < 300:
                print(
                    "Zoho CRM updated | deal_id=",
                    crm_deal_id,
                    "technician=",
                    technician_name,
                )
            else:
                print("ZOHO ERROR:", resp.text)
        except Exception as exc:
            print("ZOHO ERROR (CRM update):", exc)
        finally:
            time.sleep(0.2)
