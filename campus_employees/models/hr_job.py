from odoo import api, fields, models


class HrJob(models.Model):
    _inherit = 'hr.job'

    academic_role = fields.Selection([
        ('lecturer', 'Lecturer'),
        ('pmb', 'PMB Staff'),
        ('academic', 'Academic Staff (TU)')
    ], string="Academic Role")

    @api.model
    def _name_search(self, name, domain=None, operator='ilike', limit=None, order=None):
        domain = list(domain or [])
        if self.env.context.get('default_academic_role'):
            domain.append(('academic_role', '=', self.env.context.get('default_academic_role')))
            
        return super()._name_search(name, domain, operator, limit, order)
