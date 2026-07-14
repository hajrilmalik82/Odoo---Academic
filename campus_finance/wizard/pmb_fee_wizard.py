from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PmbFeeWizard(models.TransientModel):
    _name = 'pmb.fee.wizard'
    _description = 'Set PMB Registration Fee'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, readonly=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related='company_id.currency_id')
    pmb_registration_fee = fields.Float(string='PMB Registration Fee')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'pmb_registration_fee' in fields_list:
            res['pmb_registration_fee'] = self.env.company.pmb_registration_fee
        return res

    @api.constrains('pmb_registration_fee')
    def _check_fee(self):
        for record in self:
            if record.pmb_registration_fee < 0:
                raise ValidationError(_("Registration fee cannot be negative."))

    def action_save(self):
        self.ensure_one()
        self.company_id.sudo().pmb_registration_fee = self.pmb_registration_fee
        return {'type': 'ir.actions.act_window_close'}
