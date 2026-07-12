from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    pmb_registration_fee = fields.Float(string='PMB Registration Fee', default=250000.0, help='The default fee for new student admissions.')
