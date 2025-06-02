frappe.call({
  method: 'genixwhats.overrides.notifications.get_all_doctypes',
  callback: function(r) {
    (r.message || []).forEach(doctype => {
      frappe.ui.form.on(doctype, {
        refresh: function(frm) {
          if (frm._whatsapp_btn_added) return;
          frm._whatsapp_btn_added = true;


          if (!$('#whatsapp-loader').length) {
            $('body').append('<div id="whatsapp-loader"></div>');
          }

          frm.add_custom_button(__('Send WhatsApp PDF'), () => {
            frappe.call({
              method: 'genixwhats.overrides.notifications.get_whatsapp_notifications',
              args: { doctype },
              callback: res => {
                if (!(res.message || []).length) {
                  frappe.msgprint(__('No WhatsApp notifications available.'));
                  return;
                }

                let d = new frappe.ui.Dialog({
                  title: __('Select WhatsApp Notification'),
                  fields: [{
                    label: __('Notification'),
                    fieldname: 'notification',
                    fieldtype: 'Select',
                    options: res.message.map(n => ({
                      label: n.subject || n.name,
                      value: n.name
                    }))
                  }],
                  primary_action_label: __('Send'),
                  primary_action(values) {
                    if (!values.notification) {
                      frappe.msgprint(__('Please select a notification.'));
                      return;
                    }
                    d.hide();
                    $('#whatsapp-loader').show();

                    frappe.call({
                      method: 'genixwhats.overrides.notifications.send_whatsapp_file',
                      args: {
                        docname: frm.doc.name,
                        doctype: frm.doc.doctype,
                        notification_name: values.notification
                      },
                      callback: () => {
                        $('#whatsapp-loader').hide();
                        frappe.show_alert({
                          message: __('Sent via: ' + values.notification),
                          indicator: 'green'
                        });
                      },
                      error: () => {
                        $('#whatsapp-loader').hide();
                        frappe.show_alert({
                          message: __('Error while sending via: ' + values.notification),
                          indicator: 'red'
                        });
                      }
                    });
                  }
                });
                d.show();
              }
            });
          }).addClass('btn-primary');
        }
      });
    });
  }
});

