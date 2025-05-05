import frappe
from frappe import _
from frappe.utils.pdf import get_pdf
from frappe.email.doctype.notification.notification import Notification, get_context, json
import requests
import os

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

        for receipt in recipients:
            number = receipt
            if "{" in number:
                number = frappe.render_template(receipt, context)

            message = frappe.render_template(self.message, context)
            phone_number = self.get_receiver_phone_number(number)
            sent_numbers.append(phone_number)

            if self.attach_print and self.print_format:
                file_path = self.generate_pdf(doc)
                self.send_pdf_via_whatsapp(settings, phone_number, file_path, doc.name, message)
            else:
                text_url = f"{settings.api_url}/messages/chat"
                payload = {
                    "token": settings.token,
                    "to": phone_number,
                    "body": message,
                    "priority": "10"
                }
                headers = {"Content-Type": "application/x-www-form-urlencoded"}
                resp = requests.post(text_url, data=payload, headers=headers)
                frappe.logger().info(f"Text message response: {resp.status_code} - {resp.text}")

        frappe.msgprint(_(f"WhatsApp message sent to: {', '.join(sent_numbers)}"))

    def generate_pdf(self, doc):
        html = frappe.get_print(
            doc.doctype,
            doc.name,
            print_format=self.print_format,
            doc=doc,
            as_pdf=False
        )
        pdf_bytes = get_pdf(html)

        site_path = frappe.utils.get_site_path()
        temp_dir = os.path.join(site_path, "private", "pdf_temp")
        os.makedirs(temp_dir, exist_ok=True)

        file_path = os.path.join(temp_dir, f"{doc.name}.pdf")
        with open(file_path, "wb") as f:
            f.write(pdf_bytes)

        return file_path

    def upload_pdf_to_ultramsg(self, settings, file_path):
        upload_url = f"{settings.api_url}/media/upload"
        payload = {'token': settings.token}
        with open(file_path, "rb") as f:
            files = {'file': f}
            response = requests.post(upload_url, data=payload, files=files, timeout=30)

        try:
            result = response.json()
        except Exception:
            frappe.log_error(f"Invalid upload response: {response.text}", "Upload JSON Error")
            return None

        frappe.logger().info(f"Upload JSON: {result}")
        uploaded_file = (
            result.get("file")
            or result.get("filename")
            or result.get("url")
            or result.get("success")
        )
        if not uploaded_file:
            frappe.log_error(f"No file key in upload response: {result}", "Upload Missing Key")
        return uploaded_file

    def send_pdf_via_whatsapp(self, settings, phone_number, file_path, doc_name, message):
        uploaded_key = self.upload_pdf_to_ultramsg(settings, file_path)
        if not uploaded_key:
            return

        doc_url = f"{settings.api_url}/messages/document"
        payload = {
            "token": settings.token,
            "to": phone_number,
            "filename": f"{doc_name}.pdf",
            "document": uploaded_key,
            "caption": message
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = requests.post(doc_url, data=payload, headers=headers, timeout=30)
        frappe.logger().info(f"Document sent response: {resp.status_code} - {resp.text}")

        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            frappe.log_error(f"Failed to delete temp PDF: {e}")

    def get_receiver_phone_number(self, number):
        num = number.replace("+", "").replace("-", "")
        if num.startswith("00"):
            num = num[2:]
        elif num.startswith("0") and len(num) == 10:
            num = "966" + num[1:]
        elif len(num) < 10:
            num = "966" + num
        if num.startswith("0"):
            num = num[1:]
        return num

