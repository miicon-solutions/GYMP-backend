from urllib.parse import urlparse

import httpx
from django.conf import settings

from core.api import BadGateway


def call(path, *, data=None, query=None):
    if not settings.SSLCOMMERZ_STORE_ID or not settings.SSLCOMMERZ_STORE_PASSWD:
        raise BadGateway(
            "Payment gateway is not configured. Set SSLCOMMERZ_STORE_ID and "
            "SSLCOMMERZ_STORE_PASSWD on the API."
        )
    host = (
        "https://sandbox.sslcommerz.com"
        if settings.SSLCOMMERZ_SANDBOX
        else "https://securepay.sslcommerz.com"
    )
    credentials = {
        "store_id": settings.SSLCOMMERZ_STORE_ID,
        "store_passwd": settings.SSLCOMMERZ_STORE_PASSWD,
    }
    try:
        with httpx.Client(timeout=30) as client:
            response = (
                client.post(host + path, data={**credentials, **data})
                if data is not None
                else client.get(
                    host + path, params={**credentials, "format": "json", "v": "1", **(query or {})}
                )
            )
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError
            return result
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise BadGateway("Payment gateway is unavailable. Try again.") from exc


def initiate(session):
    user = session.member.user
    base = settings.PUBLIC_BASE_URL
    result = call(
        "/gwprocess/v4/api.php",
        data={
            "total_amount": f"{session.amount_taka}.00",
            "currency": "BDT",
            "tran_id": session.tran_id,
            **{
                f"{outcome}_url": f"{base}/payments/return/{outcome}/?tran_id={session.tran_id}"
                for outcome in ("success", "fail", "cancel")
            },
            "ipn_url": base + "/api/v1/webhooks/sslcommerz/ipn/",
            "cus_name": user.full_name or "Member",
            "cus_email": user.email or "noreply@puregym.local",
            "cus_phone": "0" + user.phone_e164[4:],
            "cus_add1": "Dhaka",
            "cus_city": "Dhaka",
            "cus_postcode": "1000",
            "cus_country": "Bangladesh",
            "shipping_method": "NO",
            "num_of_item": "1",
            "product_name": "Titanic Gym " + session.plan.name,
            "product_category": "membership",
            "product_profile": "non-physical-goods",
            "emi_option": "0",
        },
    )
    if (
        str(result.get("status", "")).upper() != "SUCCESS"
        or urlparse(result.get("GatewayPageURL", "")).scheme != "https"
    ):
        raise BadGateway("Payment gateway is unavailable. Try again.")
    return result


def validate(val_id):
    result = call("/validator/api/validationserverAPI.php", query={"val_id": val_id})
    result.setdefault("val_id", val_id)
    return result


def query(tran_id):
    result = call("/validator/api/merchantTransIDvalidationAPI.php", query={"tran_id": tran_id})
    if str(result.get("APIConnect", "")).upper() != "DONE" or not isinstance(
        result.get("element", []), list
    ):
        raise BadGateway("Payment gateway is unavailable. Try again.")
    rows = result.get("element", [])
    if not rows:
        return {"status": "PENDING", "tran_id": tran_id}
    if any(not isinstance(row, dict) for row in rows):
        raise BadGateway("Payment gateway returned an invalid response.")
    return next(
        (row for row in rows if str(row.get("status", "")).upper() in {"VALID", "VALIDATED"}),
        rows[0],
    )
