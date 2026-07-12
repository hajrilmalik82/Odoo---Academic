from odoo import models, fields, api, _
from odoo.exceptions import UserError

class CampusAdmission(models.Model):
    _inherit = 'campus.admission'

    invoice_id = fields.Many2one('account.move', string='Registration Invoice', readonly=True, copy=False)
    
    def _create_registration_invoice(self):
        """ Creates a customer invoice for the PMB registration fee """
        self.ensure_one()
        if self.invoice_id:
            return self.invoice_id
            
        # Find or create a partner for the applicant to link the invoice
        partner = self.env['res.partner'].sudo().search([('email', '=', self.email)], limit=1)
        if not partner:
            partner = self.env['res.partner'].sudo().create({
                'name': self.name,
                'email': self.email,
            })
            
        # Find IDR currency to ensure Xendit works (include inactive)
        idr = self.env['res.currency'].sudo().with_context(active_test=False).search([('name', '=', 'IDR')], limit=1)
        if idr and not idr.active:
            idr.active = True
        
        # Registration fee (Standardized to Rp 250,000 for this simulation)
        fee_amount = 250000.0
        
        # We need an income account or a product. For simplicity, just use a line item.
        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'currency_id': idr.id if idr else self.env.company.currency_id.id,
            'ref': f"PMB Registration - {self.name}",
            'invoice_line_ids': [(0, 0, {
                'name': 'PMB Registration Fee',
                'quantity': 1,
                'price_unit': fee_amount,
            })],
        }
        
        invoice = self.env['account.move'].sudo().create(invoice_vals)
        invoice.action_post()
        
        self.sudo().write({'invoice_id': invoice.id})
        return invoice
