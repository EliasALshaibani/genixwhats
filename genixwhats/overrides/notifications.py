import frappe
from frappe import _
from frappe.email.doctype.notification.notification import Notification, get_context, json
import requests
import os
import time  
from urllib.parse import unquote

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
            if not number:
                frappe.log_error("Recipient is empty or None", "Recipient Error")
                continue

            if "{" in number:
                number = frappe.render_template(receipt, context)

            message = frappe.render_template(self.message, context)
            phone_number = self.get_receiver_phone_number(number)
            
            if self.attach_print:
                file_path = self.get_attachment_file_path(doc)
                if file_path:
                    success = self.send_pdf_via_whatsapp(settings, phone_number, file_path, doc.name, message)
                    if success:
                        sent_numbers.append(phone_number)
                    else:
                        frappe.msgprint(_(f"Failed to send attachment to {phone_number}"), alert=True)
                else:
                    frappe.msgprint(_("No PDF attachment found to send"), alert=True)
            else:
                success = self.send_text_via_whatsapp(settings, phone_number, message)
                if success:
                    sent_numbers.append(phone_number)
                else:
                    frappe.msgprint(_(f"Failed to send text message to {phone_number}"), alert=True)


            time.sleep(2)

        if sent_numbers:
            frappe.msgprint(_(f"WhatsApp message sent to: {', '.join(sent_numbers)}"))

    def get_attachment_file_path(self, doc):
        try:
            attachments = frappe.get_all("File",
                filters={
                    "attached_to_name": doc.name,
                    "attached_to_doctype": doc.doctype
                },
                fields=["file_url", "file_name"]
            )
            
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
                        file_url.lstrip("/")
                    )
                else:
                    full_path = os.path.abspath(file_url)
                
                if os.path.exists(full_path):
                    return full_path
            
            frappe.log_error("No PDF attachment found for document", "PDF Attachment Missing")
            return None
            
        except Exception as e:
            frappe.log_error(f"Error getting attachment path: {str(e)}", "Attachment Error")
            return None

    def send_text_via_whatsapp(self, settings, phone_number, message):
        try:
            text_url = f"{settings.api_url}/messages/chat"
            payload = {
                "token": settings.token,
                "to": phone_number,
                "body": message,
                "priority": "10"
            }
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            resp = requests.post(text_url, data=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            frappe.logger().info(f"Text message sent successfully to {phone_number}")
            return True
        except Exception as e:
            frappe.log_error(f"Failed to send text message to {phone_number}: {str(e)}", "WhatsApp Text Error")
            return False

    def upload_pdf(self, settings, file_path):
        upload_url = f"{settings.api_url}/media/upload"
        
        try:
            file_name = os.path.basename(file_path)
            with open(file_path, "rb") as f:
                files = {'file': (file_name, f, 'application/pdf')}
                response = requests.post(
                    upload_url,
                    data={'token': settings.token},
                    files=files,
                    timeout=30
                )

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

    def send_pdf_via_whatsapp(self, settings, phone_number, file_path, doc_name, message):
        uploaded_key = self.upload_pdf(settings, file_path)
        if not uploaded_key:
            return False

        doc_url = f"{settings.api_url}/messages/document"
        payload = {
            "token": settings.token,
            "to": phone_number,
            "filename": f"{doc_name}.pdf",
            "document": uploaded_key,
            "caption": message[:1024]
        }
        
        try:
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            resp = requests.post(doc_url, data=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            
            frappe.logger().info(f"Document sent successfully to {phone_number}: {resp.text}")
            return True
            
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
            filters={"channel": "genixwhats"},
            fields=["document_type"])
    ))

@frappe.whitelist()
def get_whatsapp_notifications(doctype):
    
    
    return frappe.get_all("Notification",
        filters={"channel": "genixwhats", "document_type": doctype},
        fields=["name", "subject"])

@frappe.whitelist()
def send_whatsapp_file(docname, doctype, notification_name):
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
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "WhatsApp Notification Error")
        frappe.throw(_("An error occurred. Contact admin."))


