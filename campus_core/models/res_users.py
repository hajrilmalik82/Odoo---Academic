from odoo import models, fields, api

class ResUsers(models.Model):
    _inherit = 'res.users'

    is_redirect_home = fields.Boolean(default=True)

    @api.depends("action_id")
    def _compute_redirect_home(self):
        super()._compute_redirect_home()
        # Force redirect to home if no specific action is set
        for user in self:
            if not user.action_id:
                user.is_redirect_home = True
