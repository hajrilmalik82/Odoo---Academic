from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


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

    @api.constrains('campus_pass_grade_point', 'campus_sessions_per_term')
    def _check_campus_settings_bounds(self):
        for record in self:
            if record.campus_pass_grade_point < 0.0 or record.campus_pass_grade_point > 4.0:
                raise ValidationError(_("Passing Grade Point must be between 0.00 and 4.00."))
            if record.campus_sessions_per_term < 1 or record.campus_sessions_per_term > 52:
                raise ValidationError(_("Sessions per Term must be between 1 and 52."))

    @api.model
    def _get_pass_grade_point(self):
        """Passing grade point, falling back to the long-standing default."""
        value = self.env['ir.config_parameter'].sudo().get_param(
            'campus_core.pass_grade_point', 2.0,
        )
        try:
            parsed = float(value)
            return min(4.0, max(0.0, parsed))
        except (TypeError, ValueError):
            return 2.0

    @api.model
    def _get_sessions_per_term(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            'campus_core.sessions_per_term', 14,
        )
        try:
            return min(52, max(1, int(value)))
        except (TypeError, ValueError):
            return 14
