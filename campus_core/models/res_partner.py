from odoo import _, api, fields, models
from odoo.fields import Domain

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
        string="Academic Advisor",
        # btree_not_null, not index=True: the column is NULL for every contact
        # that is not a student, which is most of res_partner.
        index='btree_not_null',
    )
    # restrict, not the default set-null: deleting a programme used to blank the
    # Study Program and Faculty of every student enrolled in it, without warning.
    # A programme that is no longer offered should be archived, not deleted.
    # Deliberately NO check_company here, unlike academic.subject.program_id.
    # odoo/orm/models.py:4052 reads the record's own company_id as the reference,
    # and when it is empty _check_company_domain narrows to
    # ('company_id', '=', False) - so a contact with no company may only point at
    # a programme with no company. res.partner.company_id is empty for ordinary
    # contacts while academic.program defaults to the active company, which made
    # every student contact impossible to save.
    program_id = fields.Many2one(
        'academic.program', string="Study Program", ondelete='restrict',
    )
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
    krs_ids = fields.One2many(
        'academic.krs', 'student_id', string='KRS Records'
    )

    # Counts for the stat buttons on the student form.
    #
    # No sudo here, unlike the counters on hr.employee. Those answer "what still
    # points at this person" for a guard that refuses a move, so they have to be
    # true whoever is looking. These are navigation: the number is a label on
    # the button that opens the list, and it would be worse for the two to
    # disagree. Both go through the same record rules, so they cannot.
    krs_count = fields.Integer(string="Study Plans", compute='_compute_academic_counts')
    khs_count = fields.Integer(string="Transcripts", compute='_compute_academic_counts')

    @api.depends('krs_ids', 'khs_ids')
    def _compute_academic_counts(self):
        for partner in self:
            partner.krs_count = len(partner.krs_ids)
            partner.khs_count = len(partner.khs_ids)
    cgpa = fields.Float(
        string='CGPA', compute='_compute_cgpa', store=True,
        digits=(5, 2), readonly=True
    )

    graded_credits = fields.Integer(
        string='Total Graded Credits', compute='_compute_cgpa', store=True,
        help="Credits counted towards the CGPA: one attempt per subject, the best one.",
    )
    # Deliberately not stored. It depends on the configured passing grade point,
    # which is an ir.config_parameter and so cannot appear in @api.depends; a
    # stored value would silently keep the old threshold after the registrar
    # changed it. Recomputed on read instead, which is cheap at transcript scale.
    earned_credits = fields.Integer(
        string='Credits Earned (SKS Lulus)', compute='_compute_earned_credits',
        help="Credits from subjects passed at or above the configured passing grade "
             "point. Lower than the graded total when a subject was failed and not "
             "yet repeated.",
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
    def _compute_earned_credits(self):
        """SKS Lulus: credits from subjects actually passed.

        Separate from graded_credits, which is the CGPA denominator and counts a
        failed subject too. An Indonesian transcript states both: how many
        credits were graded, and how many were earned.
        """
        pass_grade_point = self.env['res.config.settings']._get_pass_grade_point()
        for record in self:
            record.earned_credits = sum(
                line.credits
                for line in record._recognised_khs_lines()
                if line.grade_points >= pass_grade_point
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

    @api.model
    def _search_display_name(self, operator, value):
        """Let a contact be found by its student number as well as its name.

        Built with odoo.fields.Domain. The previous odoo.osv.expression is
        deprecated in 19.0 (odoo/osv/__init__.py:3-4 warns on import) and no
        stock addon imports it any more; campus_employees/models/hr_job.py in
        this same codebase already uses the replacement.
        """
        domain = super()._search_display_name(operator, value)
        if not value:
            return domain
        nim_domain = Domain('nim', operator, value)
        if operator in Domain.NEGATIVE_OPERATORS:
            # "does not contain" has to exclude NIM matches as well, so the two
            # conditions combine with AND. OR'ing a negative operator asked for
            # "name doesn't match OR nim doesn't match", which nearly every
            # partner satisfies, so the search returned the whole table.
            return domain & nim_domain
        # Positive search: match on the usual fields or on the student number.
        return domain | nim_domain

    def action_open_krs(self):
        """Creation allowed, with the student filled in. A study plan belongs to
        a student, and this is the one screen where that is already known."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Study Plans (KRS)"),
            'res_model': 'academic.krs',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': dict(self.env.context, default_student_id=self.id),
        }

    def action_open_khs(self):
        """No creation: a transcript is generated from a locked study plan in
        academic_krs.py, never typed in. New here would make an empty one that
        no plan accounts for."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Transcripts (KHS)"),
            'res_model': 'academic.khs',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': dict(self.env.context, create=False),
        }
