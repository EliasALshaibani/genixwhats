// ============================================================================
// genixwhats - button_send_whatsapp.js  (clean rewrite)
// Path: genixwhats/genixwhats/public/js/button_send_whatsapp.js
//
// WhatsApp icon-only button on every doctype that has a genixwhats notification.
// Flow on click:
//   1) Check if a 'sent' message already exists for this document.
//   2) If yes -> confirm "already sent, send again?". If no/declined -> stop.
//   3) Fetch this doctype's WhatsApp notifications:
//        - exactly one  -> send it directly
//        - more than one -> open a small selection dialog
//   4) While sending: hide the WhatsApp icon, show a spinner on the button.
//   5) On success: green alert "Sent". On failure: red alert.
// ============================================================================

(function gwInjectButtonStyle() {
  if (document.getElementById('gw-wa-btn-style')) return;
  const style = document.createElement('style');
  style.id = 'gw-wa-btn-style';
  style.textContent = `
    .gw-wa-btn .gw-wa-icon { display: inline-flex; vertical-align: middle; }
    .gw-wa-btn .gw-wa-spin {
      display: none; width: 16px; height: 16px; border-radius: 50%;
      border: 2px solid rgba(0,0,0,.2); border-top-color: #25D366;
      animation: gw-wa-spin .7s linear infinite; vertical-align: middle;
    }
    .gw-wa-btn.gw-sending { pointer-events: none; opacity: .85; }
    .gw-wa-btn.gw-sending .gw-wa-icon { display: none; }
    .gw-wa-btn.gw-sending .gw-wa-spin { display: inline-block; }
    @keyframes gw-wa-spin { to { transform: rotate(360deg); } }
  `;
  document.head.appendChild(style);
})();

// WhatsApp glyph (inline SVG) + a spinner span, both inside the button label.
const GW_WA_ICON = `
  <span class="gw-wa-icon" title="WhatsApp">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="#25D366" xmlns="http://www.w3.org/2000/svg">
      <path d="M17.47 14.38c-.3-.15-1.74-.86-2-.95-.27-.1-.46-.15-.66.15-.2.3-.76.95-.93 1.14-.17.2-.34.22-.63.07-.3-.15-1.25-.46-2.38-1.47-.88-.78-1.47-1.75-1.64-2.05-.17-.3-.02-.46.13-.6.13-.13.3-.34.44-.5.15-.18.2-.3.3-.5.1-.2.05-.37-.02-.52-.08-.15-.66-1.6-.9-2.18-.24-.57-.48-.5-.66-.5h-.57c-.2 0-.52.07-.8.37-.27.3-1.04 1.02-1.04 2.48 0 1.46 1.07 2.88 1.22 3.08.15.2 2.1 3.2 5.08 4.49.71.3 1.26.49 1.7.63.71.22 1.36.2 1.87.12.57-.08 1.74-.71 1.98-1.4.24-.68.24-1.27.17-1.39-.07-.12-.27-.2-.57-.34z"/>
      <path d="M12 2A10 10 0 0 0 3.5 17.36L2 22l4.74-1.5A10 10 0 1 0 12 2zm0 18.2a8.2 8.2 0 0 1-4.18-1.14l-.3-.18-3.1.98.98-3.02-.2-.31A8.2 8.2 0 1 1 12 20.2z"/>
    </svg>
  </span>
  <span class="gw-wa-spin"></span>
`;

frappe.call({
  method: 'genixwhats.overrides.notifications.get_all_doctypes',
  callback: function (r) {
    (r.message || []).forEach(doctype => {

      frappe.ui.form.on(doctype, {
        refresh: function (frm) {
          if (frm._gw_wa_btn_added) return;
          frm._gw_wa_btn_added = true;

          const btn = frm.add_custom_button(__('Send WhatsApp'), () => {
            gwOnClick(frm);
          });
          // Icon-only: replace the label text with the WhatsApp icon + spinner.
          btn.addClass('gw-wa-btn');
          btn.html(GW_WA_ICON);
        }
      });

      // ---- spinner helpers (operate on the button element) ----
      function gwGetBtn(frm) {
        return frm.page.wrapper.find('.gw-wa-btn').first();
      }
      function gwSetSending(frm, on) {
        const b = gwGetBtn(frm);
        if (on) b.addClass('gw-sending'); else b.removeClass('gw-sending');
      }

      // ---- main click handler ----
      function gwOnClick(frm) {
        frappe.call({
          method: 'genixwhats.overrides.notifications.gw_already_sent',
          args: { doctype: frm.doc.doctype, docname: frm.doc.name },
          callback: function (res) {
            const info = res.message || {};
            if (info.already_sent) {
              frappe.confirm(
                __('A WhatsApp message was already sent for this document. Send it again?'),
                () => gwPickAndSend(frm),   // confirmed
                () => {}                     // declined -> do nothing
              );
            } else {
              gwPickAndSend(frm);
            }
          }
        });
      }

      // ---- fetch notifications: one -> send directly, many -> dialog ----
      function gwPickAndSend(frm) {
        frappe.call({
          method: 'genixwhats.overrides.notifications.get_whatsapp_notifications',
          args: { doctype: frm.doc.doctype },
          callback: function (res) {
            const list = res.message || [];
            if (!list.length) {
              frappe.msgprint(__('No WhatsApp notifications available.'));
              return;
            }
            if (list.length === 1) {
              gwSend(frm, list[0].name);
              return;
            }
            const d = new frappe.ui.Dialog({
              title: __('Select WhatsApp Notification'),
              fields: [{
                label: __('Notification'),
                fieldname: 'notification',
                fieldtype: 'Select',
                reqd: 1,
                options: list.map(n => ({ label: n.subject || n.name, value: n.name }))
              }],
              primary_action_label: __('Send'),
              primary_action(values) {
                if (!values.notification) {
                  frappe.msgprint(__('Please select a notification.'));
                  return;
                }
                d.hide();
                gwSend(frm, values.notification);
              }
            });
            d.show();
          }
        });
      }

      // ---- the actual send: spinner on, call server, alert result ----
      function gwSend(frm, notificationName) {
        gwSetSending(frm, true);
        frappe.call({
          method: 'genixwhats.overrides.notifications.send_whatsapp_file',
          args: {
            docname: frm.doc.name,
            doctype: frm.doc.doctype,
            notification_name: notificationName
          },
          callback: function (r) {
            gwSetSending(frm, false);
            frappe.show_alert(
              { message: r.message || __('Sent'), indicator: 'green' },
              3
            );
          },
          error: function () {
            gwSetSending(frm, false);
            frappe.show_alert(
              { message: __('Sending failed'), indicator: 'red' },
              5
            );
          }
        });
      }

    });
  }
});