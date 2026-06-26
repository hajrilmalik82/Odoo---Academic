from odoo import api, fields, models

class HrJob(models.Model):
    _inherit = 'hr.job'

    is_lecturer = fields.Boolean(string="Is a Lecturer", default=False)
    is_pmb_staff = fields.Boolean(string="Is PMB Staff", default=False)

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100, **kwargs):
        domain = list(args or [])
        if 'domain' in kwargs:
            domain = list(kwargs['domain'] or [])
            
        if self.env.context.get('default_is_lecturer') or self.env.context.get('filter_lecturer'):
            domain.append(('is_lecturer', '=', True))
        elif self.env.context.get('default_is_pmb_staff') or self.env.context.get('filter_pmb'):
            domain.append(('is_pmb_staff', '=', True))
            
        # Passing positional arguments to avoid keyword argument mismatch in newer Odoo versions
        return super().name_search(name, domain, operator, limit)
