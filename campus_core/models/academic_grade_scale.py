from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AcademicGradeScale(models.Model):
    """Numeric score to letter grade and grade point.

    This was a tuple of literals on academic.khs.line, so adjusting the scale
    meant editing code. It is institution policy like the credit limits: a
    campus may use a 0-100 scale with different cut-offs, add A+ or B-, or
    change what an A is worth.

    Bands are read highest first and the first one the score reaches wins, so a
    band at 0 acts as the floor.
    """

    _name = 'academic.grade.scale'
    _description = 'Grade Scale'
    _order = 'min_score desc'
    _check_company_auto = True

    _unique_score_per_company = models.Constraint(
        'UNIQUE (min_score, company_id)',
        "Only one grade band may start at a given score.",
    )

    min_score = fields.Float(
        string='Minimum Score', digits=(5, 2), required=True,
        help="Lowest numeric score that earns this letter grade.",
    )
    letter = fields.Char(string='Letter Grade', required=True)
    grade_point = fields.Float(
        string='Grade Point', digits=(5, 2), required=True,
        help="Weight used in the GPA calculation.",
    )
    description = fields.Char(
        string='Description',
        help="Wording printed beside this band on the official transcript, "
             "for example Excellent or Pass.",
    )
    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company,
    )

    @api.model
    def _get_scale_rows(self):
        """The grading scale as the transcript prints it.

        The transcript used to carry its own copy of the nine bands as literal
        table rows, which is the one place they must not be: the moment a
        registrar edits Configuration > Grade Scale, the letters in the body of
        the document would follow the new bands while the legend underneath
        still stated the old cut-offs. An official record contradicting itself
        on the same page is unusable.

        Only the minimum of each band is stored, so the upper bound shown here
        is the next band's minimum less one. That assumes whole-number
        cut-offs, which every shipped band uses and which is how Indonesian
        campuses state a scale; a fractional cut-off would print one point low
        in the legend without affecting any grade.

        :return: list of dicts, highest band first.
        """
        bands = self.search([], order='min_score desc')
        rows = []
        for index, band in enumerate(bands):
            upper = 100.0 if index == 0 else bands[index - 1].min_score - 1
            rows.append({
                'range': '%s – %s' % (self._format_score(band.min_score),
                                      self._format_score(upper)),
                'letter': band.letter or '',
                'grade_point': '%.2f' % band.grade_point,
                'description': band.description or '',
            })
        return rows

    @staticmethod
    def _format_score(value):
        """Whole numbers without a decimal tail, so 80 reads 80 and not 80.0."""
        return '%g' % round(value, 2)

    @api.depends('letter', 'min_score', 'grade_point')
    def _compute_display_name(self):
        for record in self:
            record.display_name = _("%(letter)s (from %(score).2f, %(point).2f)") % {
                'letter': record.letter or '',
                'score': record.min_score,
                'point': record.grade_point,
            }

    @api.constrains('min_score', 'grade_point')
    def _check_values(self):
        for record in self:
            if record.min_score < 0 or record.min_score > 100:
                raise ValidationError(_("Minimum score must be between 0 and 100."))
            if record.grade_point < 0 or record.grade_point > 4:
                raise ValidationError(_("Grade point must be between 0.00 and 4.00."))

    @api.model
    def _get_grade(self, score):
        """Letter and grade point for a score.

        Falls back to the historical bottom band when nothing is configured, so
        grading never crashes on a half-set-up database. Unlike the credit limit,
        refusing here would block a lecturer mid-entry for no good reason.
        """
        band = self.search(
            [('min_score', '<=', score or 0.0)], order='min_score desc', limit=1,
        )
        if band:
            return band.letter, band.grade_point
        return 'E', 0.0
