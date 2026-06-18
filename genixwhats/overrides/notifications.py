import frappe
from frappe import _
from frappe.email.doctype.notification.notification import Notification, get_context, json
import requests
from requests.adapters import HTTPAdapter
import os
import time
import random
from urllib.parse import unquote

try:
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover
    Retry = None



GW_HTTP_TIMEOUT = 30          # HTTP request timeout for UltraMsg.

# Anti-ban protection: random delay between messages.
# Note: In synchronous mode, this delay blocks execution for its duration.
# Keep it short for testing. In production (with enqueue), increase it
# to 3–8 seconds or more for stronger account protection.
GW_DELAY_MIN = 1.0            # Minimum delay between messages (in seconds).
GW_DELAY_MAX = 3.0            # Maximum delay between messages (in seconds).

# Daily limit per number (additional anti-ban protection).
# Prevents exceeding a set number of messages per instance per day.
# 0 = disabled. Enable it (e.g., 300) in production to avoid spam.
GW_DAILY_CAP = 0

GW_PDF_GENERATOR = "chrome"


def _gw_build_session():
    # Shared requests session with automatic retries (resilient under load).
    session = requests.Session()
    if Retry is not None:
        retry = Retry(
            total=3,
            backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["POST"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
    return session


class GenixNotification(Notification):
    def validate(self):
        self.validate_for_whats_settings()
        super(GenixNotification, self).validate()

    def validate_for_whats_settings(self):
        settings = frappe.get_doc("For Whats Net Configuration")
        if self.enabled and self.channel == "genixwhats":
            if not settings.token or not settings.api_url or not settings.instance_id:
                frappe.throw(_("Please configure genixwhats settings to send WhatsApp messages"))

    def send(self, doc):
        context = get_context(doc)
        context = {"doc": doc, "alert": self, "comments": None}
        if doc.get("_comments"):
            context["comments"] = json.loads(doc.get("_comments"))

        if self.is_standard:
            self.load_standard_properties(context)

       # [Synchronous version] Direct sending (default execution path).
        try:
            if self.channel == 'genixwhats':
                self.send_whatsapp_msg(doc, context)
        except Exception:
            frappe.log_error(title='Failed to send notification', message=frappe.get_traceback())

        super(GenixNotification, self).send(doc)

    def send_whatsapp_msg(self, doc, context):
        settings = frappe.get_doc("For Whats Net Configuration")
        recipients = self.get_receiver_list(doc, context)
        sent_numbers = []
        failed_numbers = []

        session = _gw_build_session()

        # [Performance] Generate the PDF once before the loop.
        shared_pdf_path = None
        if self.attach_print:
            shared_pdf_path = self.generate_pdf(doc)
            if not shared_pdf_path:
                frappe.msgprint(_("Failed to generate PDF"), alert=True)

        try:
            for idx, receipt in enumerate(recipients):
                number = receipt
                if not number:
                    frappe.log_error("Recipient is empty or None", "Recipient Error")
                    continue

                if "{" in number:
                    number = frappe.render_template(receipt, context)

                message = frappe.render_template(self.message, context)
                phone_number = self.get_receiver_phone_number(number)

                # [Safety] Daily limit per number (if enabled).
                if GW_DAILY_CAP and not self._gw_within_daily_cap(settings):
                    frappe.msgprint(
                        _("Daily WhatsApp limit reached. Remaining messages skipped."),
                        alert=True,
                    )
                    break

                if self.attach_print:
                    if shared_pdf_path:
                        success = self.send_pdf_via_whatsapp(settings, phone_number, shared_pdf_path, doc.name, message, session=session)
                    else:
                        success = False
                else:
                    success = self.send_text_via_whatsapp(settings, phone_number, message, session=session)

                if success:
                    sent_numbers.append(phone_number)
                    self._gw_log_sent(doc, phone_number, message, success)   # [genixwhats] record in log
                    if GW_DAILY_CAP:
                        self._gw_incr_daily_count(settings)
                else:
                    failed_numbers.append(phone_number)

                
                # [Account safety] Random delay between messages (not after the last one).
                
              
                if idx < len(recipients) - 1:
                    time.sleep(random.uniform(GW_DELAY_MIN, GW_DELAY_MAX))
        finally:
            if shared_pdf_path:
                self._gw_cleanup_temp(shared_pdf_path)
            session.close()

        # [Synchronous version] Immediate notification via msgprint.
        if sent_numbers:
            frappe.msgprint(
                _("WhatsApp sent to: {0}").format(", ".join(sent_numbers))
            )
        if failed_numbers:
            frappe.msgprint(
                _("Failed for: {0}. Check Error Log.").format(", ".join(failed_numbers)),
                alert=True,
            )

    # [genixwhats] Log a sent message linked to its source document.
    # Added only to record each successful send in the log; does not affect sending.
    def _gw_log_sent(self, doc, phone_number, message, ultramsg_id=None):
        try:
            frappe.get_doc({
                "doctype": "For Whats Messages Log",
                "to_number": phone_number,
                "message_body": message,
                "status": "sent",
                "reference_doctype": doc.doctype,
                "reference_name": doc.name,
                "ultramsg_id": str(ultramsg_id) if ultramsg_id and ultramsg_id is not True else None,
            }).insert(ignore_permissions=True)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "WhatsApp Log Insert Error")

    
    # [Safety] Daily per-number limit — simple counter stored in Redis cache.
    
    def _gw_daily_key(self, settings):
        return f"gw_daily_count:{settings.instance_id}:{frappe.utils.today()}"

    def _gw_within_daily_cap(self, settings):
        try:
            current = frappe.cache().get_value(self._gw_daily_key(settings)) or 0
            return int(current) < GW_DAILY_CAP
        except Exception:
            return True  # Do not block sending on any error.

    def _gw_incr_daily_count(self, settings):
        try:
            key = self._gw_daily_key(settings)
            current = int(frappe.cache().get_value(key) or 0) + 1
            # Automatically expires after 24 hours.
            frappe.cache().set_value(key, current, expires_in_sec=86400)
        except Exception:
            pass

    
    # [PDF generation] Default to Chrome with automatic fallback.
    
    def generate_pdf(self, doc):
        try:
            print_format = self.print_format or None
            pdf_kwargs = dict(
                doctype=doc.doctype,
                name=doc.name,
                print_format=print_format,
                as_pdf=True,
                no_letterhead=0,
            )

            try:
                settings = frappe.get_cached_doc("For Whats Net Configuration")
                preferred = getattr(settings, "pdf_generator", None) or GW_PDF_GENERATOR
            except Exception:
                preferred = GW_PDF_GENERATOR

            generators = [preferred, "wkhtmltopdf" if preferred == "chrome" else "chrome"]

            last_err = None
            for gen in generators:
                try:
                    try:
                        pdf_content = frappe.get_print(pdf_generator=gen, **pdf_kwargs)
                    except TypeError:
                        pdf_content = frappe.get_print(**pdf_kwargs)
                    if pdf_content:
                        return self._gw_write_temp(doc, pdf_content)
                except Exception as e:
                    last_err = e
                    continue

            if last_err:
                raise last_err
            return None
        except Exception:
            frappe.log_error(frappe.get_traceback(), "PDF Generation Error")
            return None

    def _gw_write_temp(self, doc, pdf_content):
        file_name = f"{doc.name.replace('/', '-')}.pdf"
        temp_path = frappe.utils.get_site_path("private", "files", file_name)
        with open(temp_path, "wb") as f:
            f.write(pdf_content)
        return temp_path

    def _gw_cleanup_temp(self, file_path):
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "PDF Cleanup Error")

    # ================================================================
    # [Original - untouched] Search for existing PDF attachment
    # Legacy version functions were working differently and kept for reuse if needed later.
    # ================================================================
    def get_attachment_file_path(self, doc):
        try:
            attachments = frappe.get_all("File",
                filters={"attached_to_name": doc.name, "attached_to_doctype": doc.doctype},
                fields=["file_url", "file_name"])
            if not attachments:
                frappe.log_error("No attachments found for document", "Attachment Missing")
                return None
            for attachment in attachments:
                file_url = attachment.get("file_url")
                if not file_url:
                    continue
                file_url = unquote(file_url)
                if not file_url.lower().endswith('.pdf'):
                    continue
                if file_url.startswith(('/files/', '/private/files/')):
                    site_path = frappe.utils.get_site_path()
                    full_path = os.path.join(
                        site_path,
                        'public' if file_url.startswith('/files/') else '',
                        file_url.lstrip("/"))
                else:
                    full_path = os.path.abspath(file_url)
                if os.path.exists(full_path):
                    return full_path
            frappe.log_error("No PDF attachment found for document", "PDF Attachment Missing")
            return None
        except Exception as e:
            frappe.log_error(f"Error getting attachment path: {str(e)}", "Attachment Error")
            return None

    def send_text_via_whatsapp(self, settings, phone_number, message, session=None):
        try:
            http = session or requests
            text_url = f"{settings.api_url}/messages/chat"
            payload = {"token": settings.token, "to": phone_number, "body": message, "priority": "10"}
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            resp = http.post(text_url, data=payload, headers=headers, timeout=GW_HTTP_TIMEOUT)
            resp.raise_for_status()
            frappe.logger().info(f"Text message sent successfully to {phone_number}")
            data = resp.json() if resp.content else {}
            return data.get("id") or True
        except Exception as e:
            frappe.log_error(f"Failed to send text message to {phone_number}: {str(e)}", "WhatsApp Text Error")
            return False

    def upload_pdf(self, settings, file_path, session=None):
        http = session or requests
        upload_url = f"{settings.api_url}/media/upload"
        try:
            file_name = os.path.basename(file_path)
            with open(file_path, "rb") as f:
                files = {'file': (file_name, f, 'application/pdf')}
                response = http.post(upload_url, data={'token': settings.token}, files=files, timeout=GW_HTTP_TIMEOUT)
            response.raise_for_status()
            result = response.json()
            frappe.logger().info(f"Upload response: {result}")
            uploaded_file = result.get("success")
            if not uploaded_file:
                frappe.log_error(f"No valid file identifier in response: {result}", "Upload Missing Key")
                return None
            return uploaded_file
        except Exception as e:
            frappe.log_error(f"Failed to upload file: {str(e)}", "File Upload Error")
            return None

    def send_pdf_via_whatsapp(self, settings, phone_number, file_path, doc_name, message, session=None):
        http = session or requests
        uploaded_key = self.upload_pdf(settings, file_path, session=session)
        if not uploaded_key:
            return False
        doc_url = f"{settings.api_url}/messages/document"
        payload = {
            "token": settings.token, "to": phone_number,
            "filename": f"{doc_name}.pdf", "document": uploaded_key, "caption": message[:1024]}
        try:
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            resp = http.post(doc_url, data=payload, headers=headers, timeout=GW_HTTP_TIMEOUT)
            resp.raise_for_status()
            frappe.logger().info(f"Document sent successfully to {phone_number}: {resp.text}")
            data = resp.json() if resp.content else {}
            return data.get("id") or True
        except Exception as e:
            frappe.log_error(f"Failed to send document to {phone_number}: {str(e)}", "Document Send Error")
            return False

    def get_receiver_phone_number(self, number):
        if not number:
            frappe.log_error("No phone number provided", "Phone Number Error")
            return ''
        num = ''.join(c for c in number if c.isdigit())
        if num.startswith('00'):
            num = num[2:]
        elif num.startswith('0') and len(num) == 10:
            num = '966' + num[1:]
        elif len(num) < 10:
            num = '966' + num
        if num.startswith('0'):
            num = num[1:]
        return num


@frappe.whitelist()
def get_all_doctypes():
    return list(set(
        d.document_type for d in frappe.get_all("Notification",
            filters={"channel": "genixwhats"}, fields=["document_type"])))

@frappe.whitelist()
def get_whatsapp_notifications(doctype):
    return frappe.get_all("Notification",
        filters={"channel": "genixwhats", "document_type": doctype},
        fields=["name", "subject"])

@frappe.whitelist()
def get_whatsapp_events(doctype):
    # ================================================================
    # [genixwhats integration] Returns enabled notification events for this DocType
    # (Save/Submit/Cancel/New...). Used by the UI to dynamically display indicators
    # based on Send Alert On settings without modifying core code.
    # ================================================================
    rows = frappe.get_all(
        "Notification",
        filters={"channel": "genixwhats", "document_type": doctype, "enabled": 1},
        fields=["event"],
    )
    return list({(r.event or "").strip() for r in rows if r.event})


@frappe.whitelist()
def send_whatsapp_file(docname, doctype, notification_name):
    # [Synchronous version] Immediate direct sending.
    try:
        if not frappe.has_permission(doctype, "read", doc=docname):
            frappe.throw(_("You do not have permission."))

        doc = frappe.get_doc(doctype, docname)
        notification_doc = frappe.get_doc("Notification", notification_name)
        notification = GenixNotification(notification_doc.as_dict())

        if notification.channel != "genixwhats":
            frappe.throw(_("Invalid notification channel."))

        notification.send_whatsapp_msg(doc, {"doc": doc, "alert": notification})
        return _("WhatsApp message sent.")
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp Notification Error")
        frappe.throw(_("An error occurred. Contact admin."))

@frappe.whitelist()
def gw_already_sent(doctype, docname):
    # [genixwhats] Check whether a 'sent' WhatsApp message already exists
    # for this document (used by the button to confirm re-sending).
    count = frappe.db.count(
        "For Whats Messages Log",
        filters={
            "reference_doctype": doctype,
            "reference_name": docname,
            "status": "sent",
        },
    )
    return {"already_sent": count > 0, "count": count}
