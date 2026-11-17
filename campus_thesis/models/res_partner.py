from odoo import _, api, fields, models


class ResPartner(models.Model):
    """Thesis linkage and curriculum eligibility queries on student contacts."""

    _inherit = 'res.partner'

    thesis_ids = fields.One2many(
        'campus.thesis', 'student_id', string='Theses',
    )
    thesis_count = fields.Integer(
        string='Thesis Count', compute='_compute_thesis_count',
    )

    @api.depends('thesis_ids')
    def _compute_thesis_count(self):
        for partner in self:
            partner.thesis_count = len(partner.thesis_ids)

    def _has_passed_research_method(self):
        """Whether this student has passed a Research Methodology subject in KHS.

        Evaluated with sudo() so a portal student or a prospective Thesis
        Supervisor (who has no KHS read rule on subjects they do not teach) gets
        an accurate eligibility decision without bypassing any guard.
        """
        self.ensure_one()
        pass_grade_point = self.env['res.config.settings']._get_pass_grade_point()
        return bool(self.env['academic.khs.line'].sudo().search_count([
            ('khs_id.student_id', '=', self.id),
            ('is_graded', '=', True),
            ('grade_points', '>=', pass_grade_point),
            ('subject_id.thesis_role', '=', 'research_method'),
        ]))

    def _has_enrolled_thesis_subject(self):
        """Whether this student is enrolled in a Thesis subject in an approved/locked KRS."""
        self.ensure_one()
        return bool(self.env['academic.krs.line'].sudo().search_count([
            ('krs_id.student_id', '=', self.id),
            ('krs_id.state', 'in', ('approved', 'locked')),
            ('subject_id.thesis_role', '=', 'thesis'),
        ]))

    def action_open_thesis(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Student Theses"),
            'res_model': 'campus.thesis',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': dict(self.env.context, default_student_id=self.id),
        }
