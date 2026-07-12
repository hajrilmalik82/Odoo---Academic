from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pmb_registration_fee = fields.Float(
        related='company_id.pmb_registration_fee', 
        readonly=False,
        string='PMB Registration Fee',
        help='The fee charged to prospective students when they submit the PMB form.'
    )
