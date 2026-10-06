from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AcademicCreditLimit(models.Model):
    """How many credits a student may take, by CGPA band.

    This used to be an if/elif ladder inside academic.krs with the thresholds
    and the credit caps written as literals, so changing campus policy meant
    changing code and redeploying. It is ordinary master data: registrars adjust
    it, often between terms, and it differs per institution.

    Bands are read highest first and the first one the student's CGPA reaches
    wins, so a band at 0.0 acts as the floor for everyone else.
    """

    _name = 'academic.credit.limit'
    _description = 'Credit Limit by CGPA'
    _order = 'min_cgpa desc'
    _check_company_auto = True

    _unique_band_per_company = models.Constraint(
        'UNIQUE (min_cgpa, company_id)',
        "Only one credit limit band may start at a given CGPA.",
    )

    min_cgpa = fields.Float(
        string='Minimum CGPA', digits=(5, 2), required=True,
        help="Lowest CGPA that qualifies for this credit limit.",
    )
    max_credits = fields.Integer(
        string='Maximum Credits (SKS)', required=True,
        help="Most credits a student in this band may register in one term.",
    )
    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company,
    )

    @api.depends('min_cgpa', 'max_credits')
    def _compute_display_name(self):
        for record in self:
            record.display_name = _("CGPA %(cgpa).2f and above: %(credits)s SKS") % {
                'cgpa': record.min_cgpa,
                'credits': record.max_credits,
            }

    @api.constrains('min_cgpa', 'max_credits')
    def _check_values(self):
        for record in self:
            if record.min_cgpa < 0 or record.min_cgpa > 4:
                raise ValidationError(_("Minimum CGPA must be between 0.00 and 4.00."))
            if record.max_credits <= 0:
                raise ValidationError(_("Maximum credits must be greater than zero."))

    @api.model
    def _get_max_credits(self, cgpa):
        """Credit cap for a CGPA, or None when no band is configured."""
        band = self.search(
            [('min_cgpa', '<=', cgpa or 0.0)], order='min_cgpa desc', limit=1,
        )
        return band.max_credits if band else None
