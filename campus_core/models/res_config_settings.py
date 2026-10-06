from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    """Academic policy that used to be literals scattered through the code.

    The pass threshold appeared as a bare 2.0 inside the prerequisite query, and
    the session count as range(14) buried in a method body. Both are institution
    policy, not constants: changing either meant editing code and redeploying.
    """

    _inherit = 'res.config.settings'

    campus_pass_grade_point = fields.Float(
        string='Passing Grade Point',
        config_parameter='campus_core.pass_grade_point',
        default=2.0,
        digits=(5, 2),
        help="Lowest grade point that counts as a pass. Used to decide whether a "
             "prerequisite has been met and which credits count as earned.",
    )
    campus_sessions_per_term = fields.Integer(
        string='Sessions per Term',
        config_parameter='campus_core.sessions_per_term',
        default=14,
        help="How many weekly meetings Generate Sessions creates for a class.",
    )

    @api.model
    def _get_pass_grade_point(self):
        """Passing grade point, falling back to the long-standing default."""
        value = self.env['ir.config_parameter'].sudo().get_param(
            'campus_core.pass_grade_point', 2.0,
        )
        try:
            return float(value)
        except (TypeError, ValueError):
            return 2.0

    @api.model
    def _get_sessions_per_term(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            'campus_core.sessions_per_term', 14,
        )
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 14
