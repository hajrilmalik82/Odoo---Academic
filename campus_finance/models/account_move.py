from odoo import api, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _compute_payment_state(self):
        super()._compute_payment_state()
        paid_invoices = self.filtered(
            lambda m: m.payment_state in ('paid', 'in_payment')
            and m.move_type == 'out_invoice'
        )
        if not paid_invoices:
            return

        admissions = self.env['campus.admission'].sudo().search([
            ('invoice_id', 'in', paid_invoices.ids),
            ('state', '=', 'draft'),
        ])
        for admission in admissions:
            admission.write({'state': 'submitted'})
            admission.message_post(
                body="Registration Fee Paid. Status updated to Submitted.",
            )
