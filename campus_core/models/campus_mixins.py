from odoo import api, models


class CampusSearchPanelGroupDomainMixin(models.AbstractModel):
    """Work around an Odoo 19 crash in the search panel.

    addons/web/models/models.py:1929 does
    ``AND([extra_domain, kwargs.get('group_domain', [])])`` on the many2one
    branch. The ``[]`` default only applies when the key is absent, so a client
    that sends ``group_domain: null`` reaches ``AND()`` with ``None`` and trips
    its assertion. Only a searchpanel field that is many2one, select="multi"
    and grouped can produce that, which in this codebase is academic.subject
    and campus.admission.

    The override lived in both of those models as two identical copies, with
    nothing tracking that they were one workaround rather than two decisions.
    Before that it was patched onto the 'base' abstract model, which applied it
    to every model in the database.

    Observed on Odoo 19.0 (addons/web/models/models.py:1929). Remove this mixin
    and its two _inherit entries once that is fixed upstream; a search panel on
    either model will say immediately if the fix has landed.
    """

    _name = 'campus.searchpanel.group.domain.mixin'
    _description = 'Search Panel group_domain Workaround'

    @api.model
    def search_panel_select_multi_range(self, field_name, **kwargs):
        if kwargs.get('group_domain') is None:
            kwargs['group_domain'] = []
        return super().search_panel_select_multi_range(field_name, **kwargs)
