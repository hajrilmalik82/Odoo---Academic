from odoo import Command, fields, models

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
            
        idr = self.env['res.currency'].search([('name', '=', 'IDR')], limit=1)

        # Registration fee (Configurable from Invoicing > Settings)
        fee_amount = self.env.company.pmb_registration_fee or 250000.0

        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'currency_id': idr.id if idr else self.env.company.currency_id.id,
            'ref': f"PMB Registration - {self.name}",
            'invoice_line_ids': [Command.create({
                'name': 'PMB Registration Fee',
                'quantity': 1,
                'price_unit': fee_amount,
            })],
        }
        
        invoice = self.env['account.move'].sudo().create(invoice_vals)
        invoice.action_post()
        
        self.sudo().write({'invoice_id': invoice.id})
        return invoice
