from odoo import _, api, fields, models, Command
from odoo.exceptions import AccessError, ValidationError


class AcademicKhs(models.Model):
    _name = 'academic.khs'
    _description = 'Academic Transcript (KHS)'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='KHS Number', required=True, copy=False, readonly=True, default=lambda self: 'New')
    student_id = fields.Many2one('res.partner', string='Student', required=True, domain=[('is_student', '=', True)], ondelete='restrict', index=True)
    academic_year_id = fields.Many2one('academic.year', string='Academic Year', required=True, ondelete='restrict')

    line_ids = fields.One2many('academic.khs.line', 'khs_id', string='Grade Lines')
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

    def write(self, vals):
        user = self.env.user
        is_registrar = (
            self.env.su
            or user.has_group('campus_core.group_campus_administrator')
            or user.has_group('campus_core.group_campus_academic_staff')
        )
        if not is_registrar:
            disallowed = set(vals) - {'line_ids'}
            if disallowed:
                raise AccessError(_(
                    "Lecturers can only update grade lines, not KHS details (%s)."
                ) % ', '.join(sorted(disallowed)))
            for cmd in vals.get('line_ids') or []:
                if not isinstance(cmd, (list, tuple)) or not cmd or cmd[0] not in (Command.UPDATE, Command.LINK):
                    raise AccessError(_("Lecturers cannot add, remove, or replace KHS grade lines."))
        return super().write(vals)

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
    # carried when it was taken, and stays read-only after lock.
    credits = fields.Integer(string='Credits', compute='_compute_credits', store=True, readonly=True)
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
        return self.env['academic.grade.scale'].sudo()._get_grade(score)

    @api.depends('numeric_grade', 'is_graded')
    def _compute_grade_conversion(self):
        # Bands read once per compute call, not once per line.
        bands = self.env['academic.grade.scale'].sudo().search([])
        for record in self:
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

    @staticmethod
    def _has_explicit_grade(vals):
        """Return True when vals carries a real numeric score (0.0 included, False/None excluded)."""
        return (
            'numeric_grade' in vals
            and vals['numeric_grade'] is not None
            and not isinstance(vals['numeric_grade'], bool)
        )

    @api.model_create_multi
    def create(self, vals_list):
        cleaned_vals_list = []
        for vals in vals_list:
            # A line created with an explicit numeric_grade (including 0.0) is
            # already graded; blank lines from action_lock() leave it False.
            if self._has_explicit_grade(vals):
                vals = dict(vals)
                vals.setdefault('is_graded', True)
            cleaned_vals_list.append(vals)
        return super().create(cleaned_vals_list)

    _LECTURER_WRITABLE_FIELDS = {'numeric_grade', 'is_graded'}

    def write(self, vals):
        user = self.env.user
        is_registrar = (
            self.env.su
            or user.has_group('campus_core.group_campus_administrator')
            or user.has_group('campus_core.group_campus_academic_staff')
        )
        if not is_registrar:
            disallowed = set(vals) - self._LECTURER_WRITABLE_FIELDS
            if disallowed:
                raise AccessError(_(
                    "Lecturers can only modify grade values, not transcript structure (%s)."
                ) % ', '.join(sorted(disallowed)))
        # Writing a numeric grade marks the line graded (a deliberate 0.0 included),
        # while clearing it with False/None must not flip an ungraded line to graded.
        if self._has_explicit_grade(vals):
            vals = dict(vals)
            vals.setdefault('is_graded', True)
        return super().write(vals)
