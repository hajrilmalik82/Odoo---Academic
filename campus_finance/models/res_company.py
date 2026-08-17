from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    pmb_registration_fee = fields.Monetary(string='PMB Registration Fee', default=250000.0, currency_field='currency_id', help='The default fee for new student admissions.')
