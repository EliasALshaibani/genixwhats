<div align="center">

# GenixWhats

**A native WhatsApp integration for ERPNext / Frappe — powered by UltraMsg.**

Send WhatsApp text messages and PDF attachments straight from any DocType, track every message with full delivery status, and keep everything in sync through real‑time webhooks.

[![Frappe](https://img.shields.io/badge/Frappe-v15%20%7C%20v16-0089FF)](https://frappeframework.com)
[![ERPNext](https://img.shields.io/badge/ERPNext-v15%20%7C%20v16-2490EF)](https://erpnext.com)
[![Provider](https://img.shields.io/badge/Provider-UltraMsg-25D366)](https://ultramsg.com)
[![Python](https://img.shields.io/badge/Python-%E2%89%A53.10-3776AB)](https://www.python.org)
[![License](https://img.shields.io/badge/License-MIT-green)](license.txt)

</div>

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [How It Works](#-how-it-works)
- [Data Model (DocTypes)](#-data-model-doctypes)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Enabling the Send Button (Notification Setup)](#-enabling-the-send-button-notification-setup)
- [Real‑Time Webhook](#-real-time-webhook)
- [Anti‑Ban & Safety](#-anti-ban--safety)
- [Scheduled Reconciliation](#-scheduled-reconciliation)
- [API Reference](#-api-reference)
- [License](#-license)

---

## 🧭 Overview

**GenixWhats** extends ERPNext's native **Notification** engine to add **WhatsApp** as a first‑class delivery channel. Instead of building a parallel notification system, it overrides the standard `Notification` DocType, so you keep using the same familiar interface (conditions, recipients, events, print formats) — only now your alerts can go out over WhatsApp.

Every message is dispatched through the [UltraMsg](https://ultramsg.com) API, logged inside ERPNext, linked back to its source document (Sales Invoice, Customer, etc.), and continuously kept up‑to‑date with live delivery receipts.

---

## ✨ Key Features

| Feature | Description |
|---|---|
| **Send from any DocType** | A WhatsApp button appears automatically on every document type that has a GenixWhats notification configured. |
| **Text & PDF support** | Send a plain text message, or attach the document's print format as a PDF (generated via Chrome with an automatic `wkhtmltopdf` fallback). |
| **Document linking** | Every sent message is stored and linked to its source document through a dynamic reference, so you always know what was sent and to whom. |
| **Full message log** | A dedicated DocType records the message body, sender/receiver numbers, status, delivery acknowledgements, timestamps, and the raw API response. |
| **Real‑time delivery status** | A secured webhook receives live updates from UltraMsg (`sent → delivered → read`) and updates the log instantly. |
| **Duplicate‑send guard** | Before re‑sending, the button checks whether a message was already sent for that document and asks for confirmation. |
| **Multi‑notification picker** | If a DocType has more than one WhatsApp notification, a small dialog lets the user choose which one to send. |
| **Anti‑ban protection** | Built‑in randomized delays between messages, an optional daily cap, and automatic retries with backoff. |
| **Self‑healing sync** | A scheduled reconciliation job pulls recent messages from UltraMsg every 4 hours to catch anything a missed webhook left behind. |
| **Smart number formatting** | Phone numbers are normalized automatically (handles `00`, a leading `0`, and a default country code). |

---

## ⚙️ How It Works

```
┌──────────────┐      Notification (channel = genixwhats)      ┌──────────────┐
│  ERPNext Doc │ ───────────────────────────────────────────▶ │ GenixWhats   │
│ (Invoice...) │   on save/submit OR manual "Send" button      │ Notification │
└──────────────┘                                               │  override    │
                                                               └──────┬───────┘
                                                                      │  POST (text/PDF)
                                                                      ▼
                                                              ┌───────────────┐
                                                              │  UltraMsg API │
                                                              └──────┬────────┘
                                                                     │  delivers to WhatsApp
                                                                     ▼
                                          message_ack / message_create webhook
                                                                     │
                          ┌──────────────────────────────────────────┘
                          ▼
                 ┌─────────────────────┐        every 4h reconciliation
                 │ For Whats Messages  │ ◀───────────────────────────────
                 │        Log          │   (safety net for missed events)
                 └─────────────────────┘
```

1. **Trigger** — A message is sent either automatically (on a Notification event such as *New / Save / Submit*) or manually via the WhatsApp button on the form.
2. **Dispatch** — `GenixNotification` renders the message template, normalizes the recipient number, optionally generates a PDF, and posts to UltraMsg.
3. **Log** — Each successful send is written to **For Whats Messages Log**, linked to its source document.
4. **Track** — UltraMsg calls back via the webhook to update delivery acknowledgements in real time.
5. **Reconcile** — A scheduled job fills any gaps the webhook may have missed.

---

## 🗂️ Data Model (DocTypes)

GenixWhats ships with three DocTypes.

### 1. `For Whats Net Configuration` (Single)

The central settings document holding your UltraMsg credentials and webhook details.

| Field | Type | Required | Description |
|---|---|:---:|---|
| `api_url` | Data | ✅ | UltraMsg instance API base URL (e.g. `https://api.ultramsg.com/instanceXXXX`). |
| `instance_id` | Data | ✅ | Your UltraMsg instance ID. |
| `token` | Data | ✅ | UltraMsg API token used to authenticate every request. |
| `webhook_secret` | Password | — | Auto‑generated secret that protects the incoming webhook. |
| `webhook_url` | Small Text (read‑only) | — | The full, ready‑to‑copy webhook URL (built automatically from your site URL + secret). |

> The webhook secret is generated automatically on first save.

**Buttons available on this screen:**

| Button | Function |
|---|---|
| **Copy Webhook URL** | Copies the full webhook URL to the clipboard in one click, ready to paste into UltraMsg. (Shown only after the URL has been generated.) |
| **Regenerate Secret** | Regenerates the `webhook_secret` and updates the URL automatically. It asks for confirmation first, and after regenerating you must update the new URL in UltraMsg. Use it if the secret leaks or you want to rotate it periodically. |

### 2. `For Whats Messages Log`

The audit trail. One record per message, created on send and updated by the webhook / sync.

| Field | Type | Description |
|---|---|---|
| `ultramsg_id` | Data *(unique)* | The unique message ID returned by UltraMsg. |
| `to_number` | Data | Recipient phone number. |
| `from_number` | Data | Sender (your instance) number. |
| `message_body` | Small Text | The message text / caption that was sent. |
| `message_type` | Data | Message type (chat, document, etc.). |
| `status` | Select | `sent` · `queue` · `unsent`. |
| `ack` | Data | Delivery acknowledgement (`pending → server → device → read → played`). |
| `priority` | Int | Message priority. |
| `created_on` | Datetime | When the message was created. |
| `sent_on` | Datetime | When the message was sent. |
| `raw_response` | Small Text | Full raw JSON returned by UltraMsg (for debugging/auditing). |
| `reference_doctype` | Link → DocType | The source document type. |
| `reference_name` | Dynamic Link | The exact source document the message belongs to. |

### 3. `For Whats Messages`

A lightweight contact helper for ad‑hoc recipients.

| Field | Type | Required | Description |
|---|---|:---:|---|
| `phone` | Phone | ✅ | The recipient's phone number. |
| `receiver_name` | Small Text | — | A friendly name for the recipient. |

---

## 💾 Installation

Install with the **bench CLI**:

```bash
cd $PATH_TO_YOUR_BENCH

# Fetch the app
bench get-app https://github.com/EliasALshaibani/genixwhats --branch develop

# Install it on your site
bench --site your-site.local install-app genixwhats
```

**Requirements:**
- **ERPNext / Frappe v15** → Python ≥ 3.10
- **ERPNext / Frappe v16** → Python 3.14 (`>=3.14,<3.15`) and Node.js 24

For PDF sending, a working PDF generator is required (Chrome headless is preferred; `wkhtmltopdf` is used as a fallback).

---

## 🔧 Configuration

1. Open **For Whats Net Configuration** in ERPNext.
2. Fill in `API URL`, `Instance ID`, and `Token` from your UltraMsg dashboard.
3. **Save** — a `webhook_secret` and the full `webhook_url` are generated automatically.
4. Click **Copy Webhook URL** and paste it into your UltraMsg instance's webhook settings.

---

## 🔔 Enabling the Send Button (Notification Setup)

GenixWhats does not add a new DocType for sending — it relies on Frappe's standard **Notification** DocType after overriding it. So all sending options are configured by creating a **Notification** from: (Settings → Notifications / `Notification`).

Below is a complete reference for every field on the screen, with its relation to GenixWhats.

### Core Fields

| Field | Fieldname | Description |
|---|---|---|
| **Enabled** | `enabled` | Enables the notification. Must be on for the WhatsApp button to appear and for sending to work. |
| **Is Standard** | `is_standard` | Usually set for notifications shipped with apps (developers). Leave it off for notifications you create manually. |
| **Channel** | `channel` | **Must be set to `genixwhats`** — this is the channel that enables WhatsApp sending. |
| **Document Type** | `document_type` | The document type the button appears on and the notification is sent from (Sales Invoice, Customer, etc.). |
| **Send System Notification** | `send_system_notification` | If enabled, the notification also appears in the notifications dropdown at the top‑right of ERPNext. |

### When Is It Sent? (Send Alert On)

The **`event`** field defines what automatically triggers sending:

| Option | Meaning |
|---|---|
| **New** | When a new document is created. |
| **Save** | When the document is saved. |
| **Submit** | When the document is submitted. |
| **Cancel** | When the document is cancelled. |
| **Days After / Days Before** | A number of days after/before a given date field. |
| **Minutes After / Minutes Before** | A number of minutes after/before a given datetime field. |
| **Value Change** | When a specific field's value changes. |
| **Method / Custom** | On a custom programmatic call. |

> Besides automatic event‑based sending, you can always send **manually** via the WhatsApp button on the document.

### Recipients

A child table that defines who receives the message, with the same logic as standard ERPNext notifications:

| Column | Fieldname | Purpose |
|---|---|---|
| **Receiver By Document Field** | `receiver_by_document_field` | The field on the document that holds the recipient's **phone number** (e.g. `custom_customer_phone`). This is the key one for WhatsApp sending. |
| **Receiver By Role** | `receiver_by_role` | (Optional) send to all users holding a given role. |
| **Condition** | `condition` | (Optional) a condition specific to this recipient row. |

### Message

The **`message`** field is the message template and supports **Jinja** to access document fields. Example:

```html
<h3>Order Overdue</h3>
<p>Transaction {{ doc.name }} has exceeded its Due Date. Please take the necessary action.</p>

{% if comments %}
Last comment: {{ comments[-1].comment }} by {{ comments[-1].by }}
{% endif %}

<ul>
  <li>Customer: {{ doc.customer }}</li>
  <li>Amount: {{ doc.grand_total }}</li>
</ul>
```

### Attachment Settings

| Field | Fieldname | Description |
|---|---|---|
| **Attach Print** | `attach_print` | Enable to send the document as a **PDF** alongside the message (the message text is used as the caption). |
| **Print Format** | `print_format` | Determines **which print format is sent over WhatsApp** as a PDF. If left empty, the document's default format is used. |
| **Attach Files** | `attach_files` | Attach the document's files: **From Field** (a specific field) or **All** (all attachments). |

### After Saving

Once the notification is saved, a green **WhatsApp** icon button appears on the chosen DocType. Clicking it:
1. Checks whether a message was already sent for the document (and asks before re‑sending).
2. Sends the single matching notification directly, or shows a picker if several exist for the same document.
3. Displays a spinner while sending, then a success/failure alert.

---

## 🌐 Real‑Time Webhook

The webhook endpoint receives live events from UltraMsg and updates the log in the background:

- **`message_ack`** — advances the delivery status (forward‑only: a newer status is never overwritten by an older one).
- **`message_create` / `message_received`** — upserts the full message record.

Security & reliability:
- Every request is validated against the `webhook_secret`; unauthorized calls are rejected.
- Processing is **enqueued** to a background worker so the endpoint always responds quickly.
- Status updates use atomic field writes to stay safe under concurrent webhook calls.

---

## 🛡️ Anti‑Ban & Safety

To protect your WhatsApp number from being flagged, GenixWhats includes several safeguards (configurable in `overrides/notifications.py`):

| Mechanism | Default | Purpose |
|---|---|---|
| **Randomized delay** | 1–3 s between messages | Avoids robotic, evenly‑timed bursts. |
| **Daily cap per number** | Disabled (`0`) | Optionally limit messages per instance per day (e.g. `300`). |
| **Automatic retries** | 3 attempts, backoff | Resilient against transient `429/5xx` errors. |
| **HTTP timeout** | 30 s | Prevents hung requests. |

---

## ⏱️ Scheduled Reconciliation

A cron job runs **every 4 hours** (`0 */4 * * *`) and pulls recent messages from UltraMsg to back‑fill anything the webhook may have missed. It is wrapped in error handling so a failure can never break the scheduler.

---

## 📡 API Reference

Whitelisted methods you can call from the client or other apps:

| Method | Purpose |
|---|---|
| `...notifications.send_whatsapp_file` | Send a notification for a specific document immediately. |
| `...notifications.get_all_doctypes` | List all DocTypes that have a GenixWhats notification. |
| `...notifications.get_whatsapp_notifications` | List WhatsApp notifications for a given DocType. |
| `...notifications.get_whatsapp_events` | Return the enabled notification events for a DocType. |
| `...notifications.gw_already_sent` | Check whether a message was already sent for a document. |
| `...ultramsg_sync.ultramsg_webhook` | Public webhook entry point (secret‑protected). |
| `...ultramsg_sync.sync_once` / `sync_all` | Manually pull messages from UltraMsg into the log. |
| `...ultramsg_sync.test_connection` | Verify connectivity with UltraMsg. |
| `...for_whats_net_configuration.regenerate_webhook_secret` | Rotate the webhook secret. |

*(Full path prefix: `genixwhats.overrides` / `genixwhats.genixwhats.doctype.for_whats_net_configuration`.)*

---

## 📄 License

Released under the **MIT License**. See [license.txt](license.txt) for details.

---

<div align="center">

Made with 💚 for the ERPNext community.

</div>
