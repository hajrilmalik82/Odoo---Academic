from odoo import models
class AccountMove(models.Model):
    _inherit = 'account.move'
        
    def write(self, vals):
        res = super().write(vals)
        for move in self:
            if move.payment_state in ('paid', 'in_payment'):
                # Find if this invoice is linked to an admission
                admission = self.env['campus.admission'].sudo().search([('invoice_id', '=', move.id)], limit=1)
                if admission and admission.state == 'draft':
                    # PMB Admin will review documents after payment is verified.
                    # We move state to 'submitted'
                    admission.write({'state': 'submitted'})
                    admission.message_post(body="Registration Fee Paid. Status updated to Submitted.")
        return res
