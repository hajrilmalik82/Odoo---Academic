from odoo import api, models


class Base(models.AbstractModel):
    _inherit = 'base'

    @api.model
    def search_panel_select_multi_range(self, field_name, **kwargs):
        """
        Hotfix for Odoo 19 bug where a search panel groupby with select="multi"
        passes group_domain=None and crashes the ORM AND() function.
        """
        if kwargs.get('group_domain') is None:
            kwargs['group_domain'] = []
        return super().search_panel_select_multi_range(field_name, **kwargs)
