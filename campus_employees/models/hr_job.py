from odoo import api, fields, models
from odoo.fields import Domain


class HrJob(models.Model):
    _inherit = 'hr.job'

    academic_role = fields.Selection([
        ('lecturer', 'Lecturer'),
        ('pmb', 'PMB Staff'),
        ('academic', 'Academic Staff (TU)')
    ], string="Academic Role")

    @api.model
    @api.readonly
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        """Keep the Job Position picker inside the role being hired for.

        The Lecturers / PMB Staff / Academic Staff actions put
        default_academic_role in the context, and the employee form forwards it
        to job_id. That context is what narrows this dropdown to the matching
        positions, so a lecturer cannot be handed the PMB job by accident.

        This was an override of _name_search, which Odoo 19 removed: the method
        is no longer defined anywhere in core and nothing calls it, so the
        filter silently never ran and every position was offered.

        The restriction is injected into the search domain rather than into
        _search_display_name, which looks like the natural replacement but is
        not reached when it matters most. Opening a dropdown without typing
        searches for `display_name ilike ''`, and _optimize_like_str collapses
        that condition to TRUE before the field is ever consulted, so the hook
        never fires and the unfiltered list comes back. name_search is the entry
        point the web client actually calls, through web_name_search, and the
        domain it receives is honoured whether or not anything was typed.
        """
        academic_role = self.env.context.get('default_academic_role')
        if academic_role:
            domain = Domain(domain or Domain.TRUE) & Domain('academic_role', '=', academic_role)
        return super().name_search(name, domain, operator, limit)
