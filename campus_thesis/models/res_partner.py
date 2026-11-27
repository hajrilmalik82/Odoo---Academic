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
        can_read = self.env['campus.thesis'].has_access('read')
        saved = self.filtered('id')
        counts = {}
        if saved and can_read:
            counts = {
                student.id: count
                for student, count in self.env['campus.thesis']._read_group(
                    [('student_id', 'in', saved.ids)], ['student_id'], ['__count'],
                )
            }
        for partner in self:
            partner.thesis_count = counts.get(partner.id, 0)

    @api.model
    def _students_passed_research_method(self, partner_ids):
        """Return the set of partner IDs who passed a Research Methodology subject."""
        if not partner_ids:
            return set()
        pass_grade_point = self.env['res.config.settings']._get_pass_grade_point()
        groups = self.env['academic.khs.line'].sudo()._read_group(
            [
                ('khs_id.student_id', 'in', list(partner_ids)),
                ('is_graded', '=', True),
                ('grade_points', '>=', pass_grade_point),
                ('subject_id.thesis_role', '=', 'research_method'),
            ],
            ['khs_id.student_id'],
        )
        return {student.id for (student,) in groups if student}

    @api.model
    def _students_enrolled_thesis_subject(self, partner_ids):
        """Return the set of partner IDs enrolled in a Thesis subject in approved/locked KRS."""
        if not partner_ids:
            return set()
        groups = self.env['academic.krs.line'].sudo()._read_group(
            [
                ('krs_id.student_id', 'in', list(partner_ids)),
                ('krs_id.state', 'in', ('approved', 'locked')),
                ('subject_id.thesis_role', '=', 'thesis'),
            ],
            ['krs_id.student_id'],
        )
        return {student.id for (student,) in groups if student}

    def _has_passed_research_method(self):
        """Whether this student has passed a Research Methodology subject in KHS.

        Evaluated with sudo() so a portal student or a prospective Thesis
        Supervisor (who has no KHS read rule on subjects they do not teach) gets
        an accurate eligibility decision without bypassing any guard.
        """
        self.ensure_one()
        return self.id in self._students_passed_research_method([self.id])

    def _has_enrolled_thesis_subject(self):
        """Whether this student is enrolled in a Thesis subject in an approved/locked KRS."""
        self.ensure_one()
        return self.id in self._students_enrolled_thesis_subject([self.id])

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
