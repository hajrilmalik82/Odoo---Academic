from odoo import _, api, fields, models


from odoo.osv import expression

class ResPartner(models.Model):
    _inherit = 'res.partner'

    # A plain UNIQUE(nim, company_id) would be ineffective: PostgreSQL treats
    # NULLs as distinct, and res.partner.company_id is NULL for most partners,
    # so duplicate NIMs would still slip through. COALESCE puts every
    # company-less partner in one bucket, and the WHERE clause keeps the many
    # non-student partners (nim IS NULL) out of the index entirely.
    _check_nim_unique = models.UniqueIndex(
        "(nim, COALESCE(company_id, 0)) WHERE nim IS NOT NULL",
        "Student ID (NIM) must be unique!",
    )

    is_student = fields.Boolean(string="Is a Student", default=False, index=True)
    nim = fields.Char(string="Student ID (NIM)")
    
    academic_advisor_id = fields.Many2one(
        'hr.employee', 
        string="Academic Advisor"
    )
    # restrict, not the default set-null: deleting a programme used to blank the
    # Study Program and Faculty of every student enrolled in it, without warning.
    # A programme that is no longer offered should be archived, not deleted.
    program_id = fields.Many2one('academic.program', string="Study Program", ondelete='restrict')
    faculty_id = fields.Many2one('academic.faculty', related='program_id.faculty_id', string="Faculty", store=True)
    student_status = fields.Selection([
        ('active', 'Active'),
        ('leave', 'On Leave'),
        ('graduated', 'Graduated'),
        ('dropout', 'Drop Out')
    ], default='active', string="Student Status", index=True)
    batch_year = fields.Char(string="Batch / Generation")

    khs_ids = fields.One2many(
        'academic.khs', 'student_id', string='KHS Records'
    )
    cgpa = fields.Float(
        string='CGPA', compute='_compute_cgpa', store=True,
        digits=(5, 2), readonly=True
    )

    graded_credits = fields.Integer(
        string='Total Graded Credits', compute='_compute_cgpa', store=True,
        help="Credits counted towards the CGPA: one attempt per subject, the best one.",
    )

    def _recognised_khs_lines(self):
        """The attempt that counts for each subject: one per subject, the best.

        A SIAKAD transcript recognises a subject once. When a subject is
        repeated, the recognised grade replaces the earlier attempt instead of
        sitting beside it, so the earlier one is neither averaged in nor has its
        credits counted again. The full attempt history stays visible on the
        per-semester KHS, which is where it belongs.

        Returned in transcript order: by academic year, then subject code. This
        is the single selection behind both the CGPA and the printed transcript,
        so the two cannot drift apart.

        Ungraded lines are skipped. A Float grade defaults to 0.0, which converts
        to an E, so counting them would collapse a student's CGPA the moment a
        new semester's KHS is generated.
        """
        self.ensure_one()
        best_per_subject = {}
        for khs in self.khs_ids:
            for line in khs.line_ids:
                if not line.is_graded or not line.subject_id:
                    continue
                kept = best_per_subject.get(line.subject_id.id)
                if kept is None or line.grade_points > kept.grade_points:
                    best_per_subject[line.subject_id.id] = line
        return sorted(
            best_per_subject.values(),
            key=lambda line: (
                line.khs_id.academic_year_id.name or '',
                line.subject_id.code or '',
            ),
        )

    @api.depends('khs_ids.line_ids.grade_points', 'khs_ids.line_ids.credits',
                 'khs_ids.line_ids.is_graded', 'khs_ids.line_ids.subject_id')
    def _compute_cgpa(self):
        for record in self:
            counted = record._recognised_khs_lines()
            credits = sum(line.credits for line in counted)
            points = sum(line.credits * line.grade_points for line in counted)
            record.graded_credits = credits
            record.cgpa = points / credits if credits else 0.0

    @api.depends('name')
    @api.depends_context('display_nim')
    def _compute_display_name(self):
        super()._compute_display_name()
        if self.env.context.get('display_nim'):
            for partner in self:
                if partner.nim:
                    partner.display_name = partner.nim

    @api.model
    def _search_display_name(self, operator, value):
        # Odoo 17+ menggunakan _search_display_name alih-alih _name_search
        domain = super()._search_display_name(operator, value)
        if not value:
            return domain
        nim_domain = [('nim', operator, value)]
        if operator in expression.NEGATIVE_TERM_OPERATORS:
            # "does not contain" has to exclude NIM matches as well, so the two
            # conditions combine with AND. OR'ing a negative operator asked for
            # "name doesn't match OR nim doesn't match", which nearly every
            # partner satisfies, so the search returned the whole table.
            return expression.AND([domain, nim_domain])
        # Positive search: match on the usual fields or on the student number.
        return expression.OR([domain, nim_domain])
