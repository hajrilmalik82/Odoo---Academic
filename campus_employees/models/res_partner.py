from odoo import fields, models

class ResPartner(models.Model):
    _inherit = 'res.partner'

    academic_advisor_id = fields.Many2one(
        'hr.employee', 
        string="Academic Advisor"
    )
