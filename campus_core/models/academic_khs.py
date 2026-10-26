from odoo import _, api, fields, models, Command
from odoo.exceptions import ValidationError


class AcademicKhs(models.Model):
    _name = 'academic.khs'
    _description = 'Academic Transcript (KHS)'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True

    name = fields.Char(string='KHS Number', required=True, copy=False, readonly=True, default=lambda self: 'New')
    student_id = fields.Many2one('res.partner', string='Student', required=True, domain=[('is_student', '=', True)], check_company=True, ondelete='restrict', index=True)
    academic_year_id = fields.Many2one('academic.year', string='Academic Year', required=True, check_company=True, ondelete='restrict')

    line_ids = fields.One2many('academic.khs.line', 'khs_id', string='Grade Lines')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    # Computed GPA fields.
    # total_credits is everything the student is taking this term and is what the
    # transcript and the portal show. graded_credits is the GPA denominator: only
    # the subjects a lecturer has actually marked. The two differ while a term is
    # still being graded, and that difference is the whole point.
    total_credits = fields.Integer(string='Total Credits', compute='_compute_term_gpa', store=True)
    graded_credits = fields.Integer(string='Graded Credits', compute='_compute_term_gpa', store=True)
    total_grade_points = fields.Float(string='Total Grade Points', compute='_compute_term_gpa', store=True, digits=(16, 2))
    term_gpa = fields.Float(string='Term GPA', compute='_compute_term_gpa', store=True, digits=(5, 2))

    _unique_khs = models.Constraint(
        'UNIQUE (student_id, academic_year_id)',
        "A student can only have one KHS per Academic Year!",
    )

    @api.depends('line_ids.grade_points', 'line_ids.credits', 'line_ids.is_graded')
    def _compute_term_gpa(self):
        """Average only the subjects that have actually been graded.

        Previously every line counted. Since numeric_grade is a Float it
        defaults to 0.0, which converts to an E worth 0 points, so the empty KHS
        that action_lock() generates dragged the student's GPA to zero the
        moment their KRS was locked, and the next semester's SKS limit with it.
        """
        for record in self:
            graded = record.line_ids.filtered('is_graded')
            graded_credits = sum(graded.mapped('credits'))
            total_grade_points = sum(line.credits * line.grade_points for line in graded)
            record.total_credits = sum(record.line_ids.mapped('credits'))
            record.graded_credits = graded_credits
            record.total_grade_points = total_grade_points
            record.term_gpa = total_grade_points / graded_credits if graded_credits > 0 else 0.0

    def _get_report_base_filename(self):
        """Filename for a KHS or transcript downloaded from the portal.

        Not a base-model method: portal's _show_report calls it when building the
        Content-Disposition header, and every model printed that way defines its
        own. It takes no arguments, so the transcript - which prints from this
        same model - says which document it is through the context, and the
        report action's print_report_name calls straight back into here so the
        backend Print button and the portal download cannot drift apart.
        """
        self.ensure_one()
        if self.env.context.get('campus_transcript_filename'):
            return _("Transcript - %s") % (self.student_id.name or self.name)
        return '%s - %s' % (self.name, self.student_id.name or '')

    def _schedule_grade_entry(self, lecturers):
        """Ask the lecturers of this term's classes to enter their grades.

        The 'Input Student Grades' activity type shipped with a 14-day delay and
        was never scheduled by anything, so the deadline it encoded existed only
        in the data file. One activity per lecturer, not per line: a lecturer
        teaching three of the student's subjects should be chased once.
        """
        self.ensure_one()
        activity_type = self.env.ref('campus_core.mail_activity_type_input_grades', raise_if_not_found=False)
        if not activity_type:
            return
        student_name = self.student_id.name or '-'
        for user in lecturers.user_id:
            self.activity_schedule(
                'campus_core.mail_activity_type_input_grades',
                user_id=user.id,
                summary=_("Enter grades for %s") % student_name,
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('academic.khs') or 'New'
        return super().create(vals_list)

    @api.constrains('student_id', 'academic_year_id')
    def _check_requires_approved_krs(self):
        """Ensure a KHS can only be created when an Approved or Locked KRS exists
        for the same student and academic period."""
        for record in self:
            if not record.student_id or not record.academic_year_id:
                continue
            approved_krs = self.env['academic.krs'].search_count([
                ('student_id', '=', record.student_id.id),
                ('academic_year_id', '=', record.academic_year_id.id),
                ('state', 'in', ('approved', 'locked')),
            ])
            if not approved_krs:
                raise ValidationError(
                    _("An approved KRS is required before creating a KHS for this academic period.")
                )

    @api.onchange('student_id', 'academic_year_id')
    def _onchange_student_year(self):
        if self.student_id and self.academic_year_id:
            krs = self.env['academic.krs'].search([
                ('student_id', '=', self.student_id.id),
                ('academic_year_id', '=', self.academic_year_id.id),
                ('state', 'in', ['approved', 'locked'])
            ], limit=1)

            lines = [Command.clear()]

            if krs:
                for line in krs.line_ids:
                    lines.append(Command.create({
                        'subject_id': line.subject_id.id,
                        # Carry the schedule across, as action_lock does. The
                        # lecturer record rule on academic.khs.line filters on
                        # schedule_ids.lecturer_id.user_id, so a line created
                        # without one is invisible to every lecturer and can
                        # never be graded.
                        'schedule_ids': [Command.set(line.schedule_id.ids)],
                    }))
                self.line_ids = lines
            else:
                self.line_ids = False
                return {
                    'warning': {
                        'title': _("Approved KRS Not Found"),
                        'message': _("No approved KRS found for this student in the selected academic period."),
                    }
                }


class AcademicKhsLine(models.Model):
    _name = 'academic.khs.line'
    _description = 'KHS Grade Line'

    khs_id = fields.Many2one('academic.khs', string='KHS', ondelete='cascade', index=True)
    subject_id = fields.Many2one('academic.subject', string='Subject', required=True)
    # Snapshot, not a live related: a transcript must keep the SKS the subject
    # carried when it was taken. As a related, editing a subject's credits
    # rewrote every historical KHS and silently changed past GPAs and the
    # printed transcript.
    credits = fields.Integer(string='Credits', compute='_compute_credits', store=True, readonly=False)
    schedule_ids = fields.Many2many('academic.class.schedule', string='Schedules')
    # Input field
    numeric_grade = fields.Float(string='Numeric Grade', digits=(5, 2))
    # A Float is never empty: it defaults to 0.0, and 0 is a legitimate exam
    # score. So "has this been graded?" cannot be derived from numeric_grade and
    # needs its own flag. It is set automatically when a grade is written, and
    # stays editable so a lecturer can record a genuine zero or undo a mistake.
    is_graded = fields.Boolean(string='Graded', default=False, copy=False)
    # Computed grade conversion fields
    letter_grade = fields.Char(string='Letter Grade', compute='_compute_grade_conversion', store=True)
    grade_points = fields.Float(string='Grade Points', compute='_compute_grade_conversion', store=True, digits=(5, 2))

    _unique_khs_subject = models.Constraint(
        'UNIQUE (khs_id, subject_id)',
        "The same subject cannot appear more than once in a KHS.",
    )
    _numeric_grade_range = models.Constraint(
        'CHECK (numeric_grade >= 0 AND numeric_grade <= 100)',
        "Numeric grade must be between 0 and 100.",
    )

    @api.depends('subject_id')
    def _compute_credits(self):
        for record in self:
            # Unconditional, matching academic.krs.line._compute_credits.
            record.credits = record.subject_id.credits

    @api.model
    def _get_grade_from_score(self, score):
        """Letter and grade point for a numeric score.

        The bands live in academic.grade.scale now. sudo() because a lecturer
        entering grades is reading campus configuration, not someone else's data.
        """
        return self.env['academic.grade.scale'].sudo()._get_grade(
            score, company=self.khs_id.company_id,
        )

    @api.depends('numeric_grade', 'is_graded')
    def _compute_grade_conversion(self):
        # Bands read once per compute call, not once per line. Saving a class's
        # grades in the editable list used to issue one ordered SELECT per row,
        # and a stored recompute across the whole table would have issued one per
        # historical grade. Deliberately not ormcached: academic.grade.scale is
        # master data a registrar edits, and a cache with no invalidation would
        # reintroduce the staleness this audit found elsewhere.
        Scale = self.env['academic.grade.scale'].sudo()
        bands_by_company = {}
        for record in self:
            company = record.khs_id.company_id or self.env.company
            if company.id not in bands_by_company:
                bands_by_company[company.id] = Scale.search(
                    [('company_id', 'in', [company.id, False])],
                )
        for record in self:
            company = record.khs_id.company_id or self.env.company
            bands = bands_by_company[company.id]
            if not record.is_graded:
                # Show nothing rather than a fabricated E for a subject nobody
                # has marked yet.
                record.letter_grade = ''
                record.grade_points = 0.0
                continue
            score = record.numeric_grade or 0.0
            band = next((b for b in bands if score >= b.min_score), None)
            record.letter_grade = band.letter if band else 'E'
            record.grade_points = band.grade_point if band else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # A line created carrying a real grade is already graded. A line
            # created empty is not: action_lock() generates a whole semester of
            # them, and leaving is_graded False is what stops those blanks from
            # being averaged in as zeros.
            if vals.get('numeric_grade'):
                vals.setdefault('is_graded', True)
        return super().create(vals_list)

    def write(self, vals):
        # Writing a grade marks the line graded, a deliberate 0 included.
        if 'numeric_grade' in vals:
            vals.setdefault('is_graded', True)
        return super().write(vals)
