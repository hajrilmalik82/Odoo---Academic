from odoo import api, fields, models

class HrJob(models.Model):
    _inherit = 'hr.job'

    academic_role = fields.Selection([
        ('lecturer', 'Lecturer'),
        ('pmb', 'PMB Staff'),
        ('academic', 'Academic Staff (TU)')
    ], string="Academic Role")

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100, **kwargs):
        domain = list(args or [])
        if 'domain' in kwargs:
            domain = list(kwargs['domain'] or [])
            
        if self.env.context.get('default_academic_role'):
            domain.append(('academic_role', '=', self.env.context.get('default_academic_role')))
            
        # Passing positional arguments to avoid keyword argument mismatch in newer Odoo versions
        return super().name_search(name, domain, operator, limit)
