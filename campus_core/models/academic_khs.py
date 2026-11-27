from odoo import _, api, fields, models, Command
from odoo.exceptions import AccessError, UserError, ValidationError


class AcademicKhs(models.Model):
    _name = 'academic.khs'
    _description = 'Academic Transcript (KHS)'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='KHS Number', required=True, copy=False, readonly=True, default=lambda self: 'New')
    student_id = fields.Many2one('res.partner', string='Student', required=True, domain=[('is_student', '=', True)], ondelete='restrict', index=True)
    academic_year_id = fields.Many2one('academic.year', string='Academic Year', required=True, ondelete='restrict', index=True)
    state = fields.Selection([
        ('open', 'Open'),
        ('locked', 'Finalized'),
    ], string='Status', default='open', tracking=True, index=True, copy=False)

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

    _COMPUTED_PROTECTED_FIELDS = frozenset((
        'total_credits',
        'graded_credits',
        'total_grade_points',
        'term_gpa',
    ))

    @api.depends('line_ids.grade_points', 'line_ids.credits', 'line_ids.is_graded')
    def _compute_term_gpa(self):
        """Average only the subjects that have actually been graded."""
        for record in self:
            graded = record.line_ids.filtered('is_graded')
            graded_credits = sum(graded.mapped('credits'))
            total_grade_points = sum(line.credits * line.grade_points for line in graded)
            record.total_credits = sum(record.line_ids.mapped('credits'))
            record.graded_credits = graded_credits
            record.total_grade_points = total_grade_points
            record.term_gpa = total_grade_points / graded_credits if graded_credits > 0 else 0.0

    def _get_report_base_filename(self):
        """Filename for a KHS or transcript downloaded from the portal."""
        self.ensure_one()
        if self.env.context.get('campus_transcript_filename'):
            return _("Transcript - %s") % (self.student_id.name or self.name)
        return '%s - %s' % (self.name, self.student_id.name or '')

    def _schedule_grade_entry(self, lecturers):
        """Ask the lecturers of this term's classes to enter their grades."""
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

    def action_lock_khs(self):
        """Finalize KHS records so lecturers and staff can no longer alter grades."""
        if not self.env.su and not self.env.user.has_group('campus_core.group_campus_administrator'):
            raise AccessError(_("Only Campus Administrators can finalize a KHS."))
        self.write({'state': 'locked'})

    def action_unlock_khs(self):
        """Reopen finalized KHS records for authorized grade corrections."""
        if not self.env.su and not self.env.user.has_group('campus_core.group_campus_administrator'):
            raise AccessError(_("Only Campus Administrators can reopen a finalized KHS."))
        self.write({'state': 'open'})

    @api.model_create_multi
    def create(self, vals_list):
        is_admin = self.env.su or self.env.user.has_group('campus_core.group_campus_administrator')
        cleaned = []
        for raw_vals in vals_list:
            vals = dict(raw_vals)
            if not self.env.su and self._COMPUTED_PROTECTED_FIELDS.intersection(vals):
                raise AccessError(_("Computed KHS GPA and credit totals cannot be set directly."))
            if vals.get('state') == 'locked' and not is_admin:
                raise AccessError(_("Only Campus Administrators can create finalized KHS records."))
            if not vals.get('name') or vals.get('name') == 'New':
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('academic.khs') or 'New'
            elif not is_admin:
                raise AccessError(_("KHS numbers are assigned automatically."))
            cleaned.append(vals)
        return super().create(cleaned)

    def copy(self, default=None):
        raise UserError(_(
            "KHS records cannot be duplicated. They are generated automatically when a KRS is locked."
        ))

    def write(self, vals):
        user = self.env.user
        is_admin = self.env.su or user.has_group('campus_core.group_campus_administrator')
        is_registrar = is_admin or user.has_group('campus_core.group_campus_academic_staff')
        if not self.env.su and self._COMPUTED_PROTECTED_FIELDS.intersection(vals):
            raise AccessError(_("Computed KHS GPA and credit totals cannot be modified directly."))
        if not is_admin and ('state' in vals or 'name' in vals):
            raise AccessError(_("Only Campus Administrators can change KHS status or number."))
        if not is_admin:
            locked = self.filtered(lambda rec: rec.state == 'locked')
            if locked:
                raise ValidationError(_(
                    "Finalized KHS records cannot be modified. Ask a Campus Administrator to reopen them first."
                ))
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

    def unlink(self):
        is_admin = self.env.su or self.env.user.has_group('campus_core.group_campus_administrator')
        if not is_admin:
            if self.filtered(lambda rec: rec.state == 'locked'):
                raise ValidationError(_("Finalized KHS records cannot be deleted."))
            locked_pairs = {
                (krs.student_id.id, krs.academic_year_id.id)
                for krs in self.env['academic.krs'].sudo().search([
                    ('student_id', 'in', self.mapped('student_id').ids),
                    ('academic_year_id', 'in', self.mapped('academic_year_id').ids),
                    ('state', '=', 'locked'),
                ])
            }
            for record in self:
                if (record.student_id.id, record.academic_year_id.id) in locked_pairs:
                    raise ValidationError(_(
                        "Cannot delete KHS '%s' while its study plan (KRS) is still locked. "
                        "Ask a Campus Administrator to unlock the KRS first."
                    ) % record.name)
        return super().unlink()

    @api.constrains('student_id', 'academic_year_id')
    def _check_requires_approved_krs(self):
        """Ensure a KHS can only be created when an Approved or Locked KRS exists
        for the same student and academic period."""
        relevant = self.filtered(lambda rec: rec.student_id and rec.academic_year_id)
        if not relevant:
            return
        approved_pairs = {
            (krs.student_id.id, krs.academic_year_id.id)
            for krs in self.env['academic.krs'].sudo().search([
                ('student_id', 'in', relevant.mapped('student_id').ids),
                ('academic_year_id', 'in', relevant.mapped('academic_year_id').ids),
                ('state', 'in', ('approved', 'locked')),
            ])
        }
        for record in relevant:
            if (record.student_id.id, record.academic_year_id.id) not in approved_pairs:
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
                        'credits': line.credits,
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

    khs_id = fields.Many2one('academic.khs', string='KHS', required=True, ondelete='cascade', index=True)
    subject_id = fields.Many2one('academic.subject', string='Subject', required=True, ondelete='restrict', index=True)
    # Snapshot, not a live related: a transcript must keep the SKS the subject
    # carried when it was taken. readonly=False lets action_lock() pass the
    # snapshotted KRS credits at creation while create()/write() guard against
    # non-administrator tampering.
    credits = fields.Integer(string='Credits', compute='_compute_credits', store=True, readonly=False)
    schedule_ids = fields.Many2many('academic.class.schedule', string='Schedules')
    # Input field
    numeric_grade = fields.Float(string='Numeric Grade', digits=(5, 2))
    # A Float is never empty: it defaults to 0.0, and 0 is a legitimate exam
    # score. So "has this been graded?" cannot be derived from numeric_grade and
    # needs its own flag.
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
    _credits_non_negative = models.Constraint(
        'CHECK (credits >= 0)',
        "KHS line credits cannot be negative.",
    )

    _COMPUTED_PROTECTED_FIELDS = frozenset(('letter_grade', 'grade_points'))

    @api.depends('subject_id')
    def _compute_credits(self):
        for record in self:
            record.credits = record.subject_id.credits

    @api.depends('numeric_grade', 'is_graded')
    def _compute_grade_conversion(self):
        Scale = self.env['academic.grade.scale'].sudo()
        bands = Scale.search([], order='min_score desc, id desc')
        for record in self:
            if not record.is_graded:
                record.letter_grade = ''
                record.grade_points = 0.0
                continue
            letter, point = Scale._resolve_grade(bands, record.numeric_grade or 0.0)
            record.letter_grade = letter
            record.grade_points = point

    @staticmethod
    def _has_explicit_grade(vals):
        """Return True when vals carries a real numeric score (0.0 included, False/None excluded)."""
        return (
            'numeric_grade' in vals
            and vals['numeric_grade'] is not None
            and not isinstance(vals['numeric_grade'], bool)
        )

    def _check_khs_mutable(self, khs_records):
        is_admin = self.env.su or self.env.user.has_group('campus_core.group_campus_administrator')
        if is_admin:
            return
        if khs_records.filtered(lambda khs: khs.state == 'locked'):
            raise ValidationError(_(
                "Grades cannot be modified on a finalized KHS."
            ))
        if khs_records.filtered(lambda khs: khs.student_id.student_status == 'graduated'):
            raise ValidationError(_(
                "Grades of a graduated student can only be modified by a Campus Administrator."
            ))

    @api.model_create_multi
    def create(self, vals_list):
        is_admin = self.env.su or self.env.user.has_group('campus_core.group_campus_administrator')
        if not self.env.su and any(self._COMPUTED_PROTECTED_FIELDS.intersection(vals) for vals in vals_list):
            raise AccessError(_("Letter grades and grade points are computed automatically and cannot be overridden."))
        if not is_admin:
            Subject = self.env['academic.subject'].sudo()
            for vals in vals_list:
                if 'credits' not in vals:
                    continue
                subject = Subject.browse(vals['subject_id']) if vals.get('subject_id') else Subject.browse()
                if not subject or vals['credits'] != subject.credits:
                    raise AccessError(_("Only Campus Administrators can manually override KHS line credits."))
        khs_ids = {vals['khs_id'] for vals in vals_list if vals.get('khs_id')}
        if khs_ids:
            self._check_khs_mutable(self.env['academic.khs'].browse(list(khs_ids)))
        cleaned_vals_list = []
        for vals in vals_list:
            vals = dict(vals)
            if self._has_explicit_grade(vals):
                vals.setdefault('is_graded', True)
            cleaned_vals_list.append(vals)
        return super().create(cleaned_vals_list)

    _LECTURER_WRITABLE_FIELDS = {'numeric_grade', 'is_graded'}

    def write(self, vals):
        user = self.env.user
        is_admin = self.env.su or user.has_group('campus_core.group_campus_administrator')
        is_registrar = is_admin or user.has_group('campus_core.group_campus_academic_staff')
        if not self.env.su and self._COMPUTED_PROTECTED_FIELDS.intersection(vals):
            raise AccessError(_("Letter grades and grade points are computed automatically and cannot be overridden."))
        if not is_admin and 'credits' in vals:
            Subject = self.env['academic.subject'].sudo()
            for line in self:
                target_subject = (
                    Subject.browse(vals['subject_id'])
                    if vals.get('subject_id')
                    else line.subject_id
                )
                if not target_subject or vals['credits'] != target_subject.credits:
                    raise AccessError(_("Only Campus Administrators can manually override KHS line credits."))
        self._check_khs_mutable(self.mapped('khs_id'))
        if not is_registrar:
            disallowed = set(vals) - self._LECTURER_WRITABLE_FIELDS
            if disallowed:
                raise AccessError(_(
                    "Lecturers can only modify grade values, not transcript structure (%s)."
                ) % ', '.join(sorted(disallowed)))
        if self._has_explicit_grade(vals):
            vals = dict(vals)
            vals.setdefault('is_graded', True)

        previous_grades = (
            {
                line.id: (line.is_graded, line.numeric_grade, line.letter_grade)
                for line in self
            }
            if ('numeric_grade' in vals or 'is_graded' in vals)
            else {}
        )
        res = super().write(vals)

        if previous_grades and not self.env.context.get('install_mode'):
            self._log_grade_revisions(previous_grades)
            self._close_completed_grade_activities()
        return res

    def unlink(self):
        self._check_khs_mutable(self.mapped('khs_id'))
        return super().unlink()

    def _log_grade_revisions(self, previous_grades):
        """Record an audit entry on the parent KHS chatter whenever a graded score changes."""
        for line in self:
            was_graded, old_score, old_letter = previous_grades.get(line.id, (False, 0.0, ''))
            if not was_graded:
                continue
            if line.is_graded != was_graded or line.numeric_grade != old_score:
                new_desc = (
                    _("%(score).2f (%(letter)s)") % {
                        'score': line.numeric_grade,
                        'letter': line.letter_grade or '-',
                    }
                    if line.is_graded
                    else _("Ungraded")
                )
                line.khs_id.sudo().message_post(
                    body=_(
                        "Grade updated for %(subject)s by %(user)s: %(old_score).2f (%(old_letter)s) -> %(new)s."
                    ) % {
                        'subject': line.subject_id.display_name,
                        'user': self.env.user.name,
                        'old_score': old_score,
                        'old_letter': old_letter or '-',
                        'new': new_desc,
                    }
                )

    def _close_completed_grade_activities(self):
        """Close the grade-entry activity for a lecturer once all their lines on a KHS are graded."""
        grade_type = self.env.ref('campus_core.mail_activity_type_input_grades', raise_if_not_found=False)
        if not grade_type:
            return
        for khs in self.mapped('khs_id'):
            khs_sudo = khs.sudo()
            lecturer_users = khs_sudo.line_ids.mapped('schedule_ids.lecturer_id.user_id')
            for lecturer_user in lecturer_users:
                user_lines = khs_sudo.line_ids.filtered(
                    lambda l, u=lecturer_user: u in l.schedule_ids.mapped('lecturer_id.user_id')
                )
                if user_lines and all(user_lines.mapped('is_graded')):
                    khs_sudo.activity_ids.filtered(
                        lambda act, u=lecturer_user: act.activity_type_id == grade_type and act.user_id == u
                    ).action_feedback()
