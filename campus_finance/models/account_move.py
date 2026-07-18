from odoo import _, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _invoice_paid_hook(self):
        res = super()._invoice_paid_hook()
        paid_invoices = self.filtered(lambda m: m.move_type == 'out_invoice')
        if paid_invoices:
            admissions = self.env['campus.admission'].sudo().search([
                ('invoice_id', 'in', paid_invoices.ids),
                ('state', '=', 'draft'),
            ])
            for admission in admissions:
                admission.write({'state': 'submitted'})
                admission.message_post(
                    body=_("Registration Fee Paid. Status updated to Submitted."),
                )
        return res
