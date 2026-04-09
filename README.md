# GenixWhats

> **GenixWhats** is an ERPNext app for WhatsApp integration using UltraMsg. It allows sending messages directly from ERPNext and linking them with documents like Customers and Sales Invoices.

---

## 🚀 Features

- Send WhatsApp messages directly from ERPNext.  
- Link messages to documents such as Customers and Sales Invoices.  

---


⚙️ Enabling the Send Button in ERPNext

To enable the WhatsApp send button for any Doctype in ERPNext:

Open New Notification from Settings > Notifications.
Fill in the main fields as follows:
Field	Value
Name	Any name for the button (e.g., Send WhatsApp)
Enabled	✓ (Enabled)
Is Standard	❌ (Optional)
Document Type	The Doctype where the button will appear
Channel	genixwhats
Recipients

To specify the recipients (who will receive the message) in the Notification:

No.	Receiver By Document Field	Receiver By Role	Condition	Message
1	receiver_by_document_field	receiver_by_role	condition	message
Field Descriptions:
receiver_by_document_field: The field in the Doctype that contains the recipient's phone number.
receiver_by_role: (Optional) ERPNext Role to send messages to users with that role.
condition: (Optional) Condition that determines when the message is sent.
message: The text message to send via WhatsApp.

After saving the Notification, the send button will appear inside the specified Doctype, and messages will be sent according to the recipient settings.


## 💾 Installation

You can install the app using **bench CLI**:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/EliasALshaibani/genixwhats 
bench install-app genixwhats
'''
