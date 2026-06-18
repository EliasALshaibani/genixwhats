
import frappe
import requests

CONFIG_DOCTYPE = "For Whats Net Configuration"


def get_ultramsg_settings():
   
    conf = frappe.get_doc(CONFIG_DOCTYPE)
    api_url = (conf.api_url or "").strip().rstrip("/")
    token = (conf.token or "").strip()
    if not api_url or not token:
        frappe.throw("Please set api_url and token in For Whats Net Configuration")
    return api_url, token


@frappe.whitelist()
def test_connection():
# Test: Fetches the first page of sent messages to verify the connection is working properly.
    url = f"{api_url}/messages"
    params = {"token": token, "page": 1, "limit": 5, "status": "sent", "sort": "desc"}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {
        "ok": True,
        "total": data.get("total"),
        "returned": len(data.get("messages", [])),
    }

import datetime
from frappe.utils import get_datetime


def _ts_to_datetime(value):
    if not value:
        return None
    try:
        return get_datetime(datetime.datetime.fromtimestamp(int(value)))
    except (ValueError, TypeError, OSError):
        return None


def _strip_jid(jid):
    if not jid:
        return ""
    return str(jid).split("@")[0]


def _map_fields(m):
    return {
        "ultramsg_id": str(m.get("id")),
        "from_number": _strip_jid(m.get("from")),
        "to_number": _strip_jid(m.get("to")),
        "message_body": m.get("body"),
        "message_type": m.get("type"),
        "priority": m.get("priority"),
        "status": m.get("status"),
        "ack": m.get("ack"),
        "created_on": _ts_to_datetime(m.get("created_at")),
        "sent_on": _ts_to_datetime(m.get("sent_at")),
        "raw_response": frappe.as_json(m),
    }


def _upsert_message(m):
    uid = str(m.get("id"))
    if not uid or uid == "None":
        return 0, 0
    values = _map_fields(m)
    existing = frappe.db.get_value("For Whats Messages Log", {"ultramsg_id": uid}, "name")
    if existing:
        doc = frappe.get_doc("For Whats Messages Log", existing)
        for key, val in values.items():
            doc.set(key, val)
        doc.save(ignore_permissions=True)
        return 0, 1
    doc = frappe.get_doc({"doctype": "For Whats Messages Log", **values})
    doc.insert(ignore_permissions=True)
    return 1, 0


@frappe.whitelist()
def sync_once():
    api_url, token = get_ultramsg_settings()
    url = f"{api_url}/messages"
    params = {"token": token, "page": 1, "limit": 5, "status": "sent", "sort": "desc"}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    messages = resp.json().get("messages", [])
    created = updated = 0
    for m in messages:
        c, u = _upsert_message(m)
        created += c
        updated += u
    frappe.db.commit()
    return {"created": created, "updated": updated}


@frappe.whitelist()
def sync_all(status="sent", max_pages=50, limit=100, sort="desc"):
    """يجلب كل الرسائل عبر الصفحات ويحفظها في اللوج.
    status: sent | queue | unsent | invalid | all
    max_pages: سقف أمان لعدد الصفحات.
    """
    api_url, token = get_ultramsg_settings()
    url = f"{api_url}/messages"
    max_pages = int(max_pages)
    limit = min(int(limit), 100)

    created = updated = 0
    page = 1
    while page <= max_pages:
        params = {"token": token, "page": page, "limit": limit, "status": status, "sort": sort}
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        messages = data.get("messages", []) if isinstance(data, dict) else []
        if not messages:
            break
        for m in messages:
            c, u = _upsert_message(m)
            created += c
            updated += u
        total_pages = (data.get("pages") if isinstance(data, dict) else None) or page
        if page >= total_pages:
            break
        page += 1

    frappe.db.commit()
    return {"created": created, "updated": updated, "pages_done": page}


# Webhook handler — receives real-time UltraMsg updates.

# Defines the delivery status flow (forward progression only).
_ACK_RANK = {"": 0, "pending": 1, "server": 2, "device": 3, "read": 4, "played": 5}


def _get_webhook_secret():
    return frappe.db.get_single_value("For Whats Net Configuration", "webhook_secret", cache=False) or ""


@frappe.whitelist(allow_guest=True)
def ultramsg_webhook(**kwargs):
# Main webhook entry point. Validates the secret and processes the request in the background.
    key = frappe.request.args.get("key") or frappe.form_dict.get("key")
    if not key or key != _get_webhook_secret():
        frappe.throw("Unauthorized", frappe.PermissionError)

    payload = frappe.request.get_json(silent=True) or {}
    frappe.enqueue(
        "genixwhats.overrides.ultramsg_sync.handle_webhook",
        payload=payload,
        queue="short",
        now=False,
    )
    return {"ok": True}


def handle_webhook(payload):
# Processes the UltraMsg payload in the background and updates the log.
    try:
        event_type = payload.get("event_type")
        data = payload.get("data") or {}

        uid = str(data.get("id") or "")
        if not uid:
            return

        existing = frappe.db.get_value("For Whats Messages Log", {"ultramsg_id": uid}, "name")

        # Delivery status update event (ack).
        if event_type == "message_ack":
            if not existing:
                return  # Ignore messages that are not registered in the system.
            new_ack = (data.get("ack") or "").strip()
            current_ack = (frappe.db.get_value("For Whats Messages Log", existing, "ack") or "").strip()
            # Forward-only progression rule: Do not overwrite a newer status with an older one.
            if _ACK_RANK.get(new_ack, 0) > _ACK_RANK.get(current_ack, 0):
                # Atomic field update — avoids TimestampMismatchError under concurrent webhooks.
                frappe.db.set_value("For Whats Messages Log", existing, "ack", new_ack, update_modified=False)
                frappe.db.commit()
            return

        # Message created or received event → full upsert operation.
        if event_type in ("message_create", "message_received"):
            mapped = {
                "id": data.get("id"),
                "from": data.get("from"),
                "to": data.get("to"),
                "body": data.get("body"),
                "type": data.get("type"),
                "ack": data.get("ack"),
                "priority": data.get("priority"),
                "status": data.get("status"),
                "created_at": data.get("time"),
                "sent_at": data.get("time"),
            }
            _upsert_message(mapped)
            frappe.db.commit()

    except Exception:
        frappe.log_error(frappe.get_traceback(), "UltraMsg webhook handler failed")


@frappe.whitelist()
def scheduled_sync():
    """Reconciliation job (scheduled): pulls recent messages to fill any gaps
    the webhook missed. Wrapped in try/except so a failure never breaks the scheduler."""
    try:
        return sync_all(status="all", max_pages=50)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "UltraMsg scheduled_sync failed")
