"""Read-only, privacy-minimized Shopify shipment lookup for the isolated preview.

Requires dedicated preview credentials; never reads production OS credentials or writes orders.
"""
import os
import re
import time
from urllib.parse import urlparse
import httpx

_TOKEN = {"value": "", "expires": 0.0}
ORDER_RE = re.compile(r"^#?([0-9]{4,12})(?:-C)?$", re.I)
QUERY = """query PreviewOrderTracking($search: String!) {
  orders(first: 3, query: $search) {
    nodes {
      name
      cancelledAt
      displayFulfillmentStatus
      fulfillments(first: 10) {
        status
        trackingInfo(first: 10) { company number url }
      }
    }
  }
}"""

def configured():
    return all(os.getenv(k) for k in ("SHOPIFY_STORE", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET", "SHOPIFY_API_VERSION"))

async def lookup(order_number: str) -> dict:
    match = ORDER_RE.fullmatch(order_number.strip())
    if not match:
        return {"status": "invalid", "reply": "Please enter a valid Mumchies order number (for example, 328486)."}
    if not configured():
        return {"status": "unavailable", "reply": "Live order tracking is not configured in this preview yet."}
    number = match.group(1)
    store = os.environ["SHOPIFY_STORE"].strip().removeprefix("https://").rstrip("/")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]*\.myshopify\.com", store):
        return {"status": "unavailable", "reply": "Order tracking configuration needs attention."}
    version = os.environ["SHOPIFY_API_VERSION"].strip()
    if not re.fullmatch(r"20[0-9]{2}-(01|04|07|10)", version):
        return {"status": "unavailable", "reply": "Order tracking configuration needs attention."}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if _TOKEN["expires"] <= time.monotonic():
                auth = await client.post(f"https://{store}/admin/oauth/access_token",
                    data={"grant_type": "client_credentials", "client_id": os.environ["SHOPIFY_CLIENT_ID"],
                          "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"]})
                auth.raise_for_status()
                token_data = auth.json()
                _TOKEN["value"] = token_data["access_token"]
                _TOKEN["expires"] = time.monotonic() + max(30, int(token_data.get("expires_in", 300)) - 60)
            response = await client.post(f"https://{store}/admin/api/{version}/graphql.json",
                headers={"X-Shopify-Access-Token": _TOKEN["value"]},
                json={"query": QUERY, "variables": {"search": f"name:{number}"}})
            response.raise_for_status()
            body = response.json()
            if body.get("errors"):
                raise ValueError("Shopify GraphQL error")
        orders = (body.get("data") or {}).get("orders", {}).get("nodes", [])
        exact = next((o for o in orders if str(o.get("name", "")).lstrip("#").casefold() == number.casefold()), None)
        if exact is None:
            return {"status": "not_found", "reply": "I couldn't find that order number. Please check it and try again."}
        fulfillments = exact.get("fulfillments") or []
        tracking = [t for f in fulfillments for t in (f.get("trackingInfo") or []) if t.get("number")]
        state = "Cancelled" if exact.get("cancelledAt") else str(exact.get("displayFulfillmentStatus") or "Processing").replace("_", " ").title()
        lines = [f"Order #{number}: {state}."]
        if tracking:
            t = tracking[-1]
            if t.get("company"):
                lines.append("Courier: " + str(t["company"])[:80] + ".")
            lines.append("Tracking number: " + str(t["number"])[:80] + ".")
            url = str(t.get("url") or "")
            parsed = urlparse(url)
            if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
                lines.append("Tracking link: " + url)
        else:
            lines.append("No courier tracking details are available in Shopify yet.")
        lines.append("This is the Shopify fulfillment status, not a live courier scan.")
        return {"status": "found", "reply": " ".join(lines)}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return {"status": "unavailable", "reply": "Order tracking is temporarily unavailable. Please try again later."}
