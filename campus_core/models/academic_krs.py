import logging

from odoo import _, api, fields, models, Command
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class AcademicCoursePackage(models.Model):
    _name = 'academic.course.package'
    _description = 'Academic Course Package'
    _check_company_auto = True

    name = fields.Char(string='Name', required=True)
    program_id = fields.Many2one('academic.program', string='Program', required=True)
    academic_year_id = fields.Many2one('academic.year', string='Academic Year', required=True)
    total_credits = fields.Integer(string='Total Credits', compute='_compute_total_credits', store=True)
    line_ids = fields.One2many('academic.course.package.line', 'package_id', string='Lines')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('line_ids.credits')
    def _compute_total_credits(self):
        for record in self:
            record.total_credits = sum(record.line_ids.mapped('credits'))

    @api.depends('name', 'academic_year_id')
    def _compute_display_name(self):
        for record in self:
            if record.name and record.academic_year_id:
                record.display_name = f"{record.name} - {record.academic_year_id.display_name}"
            else:
                record.display_name = record.name or ""


class AcademicCoursePackageLine(models.Model):
    _name = 'academic.course.package.line'
    _description = 'Academic Course Package Line'

    package_id = fields.Many2one('academic.course.package', string='Package', ondelete='cascade')
    program_id = fields.Many2one(related='package_id.program_id', string='Program')
    subject_id = fields.Many2one(
        'academic.subject', 
        string='Subject', 
        required=True,
        domain="[('program_id', '=', program_id)]"
    )
    credits = fields.Integer(related='subject_id.credits', string='Credits')

    _unique_subject_per_package = models.Constraint(
        'UNIQUE (package_id, subject_id)',
        "A subject can only appear once in a course package.",
    )


class AcademicKrs(models.Model):
    _name = 'academic.krs'
    _description = 'Academic KRS'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True

    name = fields.Char(string='KRS Number', required=True, copy=False, readonly=True, default=lambda self: 'New')
    student_id = fields.Many2one('res.partner', string='Student', required=True, domain=[('is_student', '=', True)], check_company=True, ondelete='restrict')
    
    academic_year_id = fields.Many2one('academic.year', string='Academic Year', required=True, check_company=True, ondelete='restrict')

    advisor_id = fields.Many2one('hr.employee', related='student_id.academic_advisor_id', string='Academic Advisor', readonly=True)
    faculty_id = fields.Many2one('academic.faculty', string='Faculty', compute='_compute_student_info', store=True, readonly=False)
    program_id = fields.Many2one('academic.program', string='Program', compute='_compute_student_info', store=True, readonly=False)

    @api.depends('student_id.program_id', 'student_id.faculty_id')
    def _compute_student_info(self):
        for record in self:
            if record.student_id:
                record.program_id = record.student_id.program_id
                record.faculty_id = record.student_id.faculty_id
            else:
                record.program_id = False
                record.faculty_id = False



    package_id = fields.Many2one('academic.course.package', string='Course Package')
    state = fields.Selection([
        ('draft', 'Draft'), 
        ('submitted', 'Waiting for Approval'), 
        ('approved', 'Approved'),
        ('revision', 'Needs Revision'),
        ('rejected', 'Rejected'),
        ('locked', 'Locked')
    ], string='Status', default='draft', group_expand='_expand_states', tracking=True, index=True, copy=False)
    
    total_credits = fields.Integer(string='Total Credits', compute='_compute_total_credits', store=True)
    line_ids = fields.One2many('academic.krs.line', 'krs_id', string='KRS Lines')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    _unique_student_academic_year_term = models.Constraint(
        'UNIQUE (student_id, academic_year_id)',
        "A student can only have one KRS per academic year.",
    )

    def _get_report_base_filename(self):
        """Filename for a KRS downloaded from the portal.

        Not a base-model method: portal's _show_report calls it when building the
        Content-Disposition header, and every model printed that way defines its
        own. Without it a student downloading their KRS would hit an AttributeError.
        """
        self.ensure_one()
        return 'KRS - %s' % (self.student_id.name or self.name)

    @api.model
    def _expand_states(self, states, domain):
        return [key for key, _val in type(self).state.selection]

    @api.model_create_multi
    def create(self, vals_list):
        is_privileged = self.env.su or self.env.user.has_group('campus_core.group_campus_administrator')
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('academic.krs') or 'New'
            if vals.get('state') and vals['state'] != 'draft' and not is_privileged:
                raise ValidationError(_("New KRS records must start in draft status."))
        return super().create(vals_list)

    @api.depends('line_ids.credits')
    def _compute_total_credits(self):
        for record in self:
            record.total_credits = sum(record.line_ids.mapped('credits'))

    def _get_max_credits_allowed(self):
        self.ensure_one()
        cgpa = self.student_id.cgpa or 0.0
        if cgpa >= 3.0:
            return 24
        if cgpa >= 2.5:
            return 21
        if cgpa >= 2.0:
            return 18
        return 15

    # A KRS is only editable while the student is still filling it in.
    _EDITABLE_STATES = ('draft', 'revision')

    def _check_content_write_allowed(self, vals):
        """Block content changes once the KRS has left the student's hands.

        This used to block the 'locked' state only, which let a student wait for
        approval on 18 SKS and then add three more subjects: nothing revalidates
        a KRS that is already submitted or approved.
        """
        protected_fields = {
            'student_id',
            'academic_year_id',
            'package_id',
            'line_ids',
        }
        if protected_fields.intersection(vals):
            frozen = self.filtered(lambda record: record.state not in self._EDITABLE_STATES)
            if frozen:
                raise ValidationError(_(
                    "A KRS can only be edited while it is in Draft or Needs Revision."
                ))

    _STATE_TRANSITIONS = {
        'draft': {'submitted'},
        'submitted': {'approved', 'revision', 'rejected'},
        'approved': {'locked', 'draft'},
        'revision': {'submitted', 'draft'},
        'rejected': {'draft'},
        'locked': {'approved'},
    }
    _PORTAL_STATE_TRANSITIONS = {('draft', 'submitted'), ('revision', 'submitted')}
    _ADMIN_STATE_TRANSITIONS = {('approved', 'locked'), ('locked', 'approved'), ('approved', 'draft')}

    def _check_state_transition_allowed(self, new_state):
        if self.env.su:
            return
        user = self.env.user
        if user.has_group('campus_core.group_campus_administrator'):
            return
        is_internal = user.has_group('base.group_user')
        for record in self:
            if record.state == new_state:
                continue
            transition = (record.state, new_state)
            if new_state not in self._STATE_TRANSITIONS.get(record.state, set()):
                raise ValidationError(_(
                    "Invalid KRS status change from '%(old_state)s' to '%(new_state)s'."
                ) % {'old_state': record.state, 'new_state': new_state})
            if not is_internal and transition not in self._PORTAL_STATE_TRANSITIONS:
                raise ValidationError(_("Students can only submit their KRS for approval."))
            if transition in self._ADMIN_STATE_TRANSITIONS:
                raise ValidationError(_("Only Campus Administrators can perform this KRS status change."))
            if transition == ('submitted', 'approved') and record.advisor_id not in user.employee_ids:
                raise ValidationError(_("Only the assigned Academic Advisor or Academic Admin can approve this KRS."))

    def write(self, vals):
        self._check_content_write_allowed(vals)
        if 'state' in vals:
            self._check_state_transition_allowed(vals['state'])
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda record: record.state == 'locked'):
            raise ValidationError(_("Locked KRS records cannot be deleted."))
        return super().unlink()

    @api.constrains('state')
    def _check_submission_requirements(self):
        """Enforce the submission rules on every path into 'submitted'.

        These checks used to live inside action_submit() only, so a student
        could skip all of them by writing the field directly over RPC
        (/web/dataset/call_kw is auth="user", and portal users are users).
        As a constraint they run on any write, import or server action, and
        crucially they still run under sudo(), unlike access rules.
        """
        submitted = self.filtered(lambda record: record.state == 'submitted')
        if submitted:
            submitted._validate_for_submission()

    def _validate_for_submission(self):
        """Every rule a KRS must satisfy to be submitted for approval."""
        # Claim the seat locks before counting anything, so two students
        # submitting into the same section cannot both read the last seat as free.
        self.mapped('line_ids.schedule_id')._lock_for_enrolment()

        # Pre-fetch ALL passed subjects for ALL students in one query to avoid N+1 queries
        student_ids = self.mapped('student_id.id')
        khs_lines = self.env['academic.khs.line'].search([
            ('khs_id.student_id', 'in', student_ids),
            ('grade_points', '>=', 2.0),
        ])
        passed_subjects_by_student = {}
        for line in khs_lines:
            passed_subjects_by_student.setdefault(line.khs_id.student_id.id, set()).add(line.subject_id.id)
            
        is_portal = not self.env.user.has_group('base.group_user')
        is_admin = self.env.user.has_group('campus_core.group_campus_administrator')
        today = fields.Date.context_today(self)

        for record in self:
            if not record.line_ids:
                raise ValidationError(_("Please add at least one class before submitting the KRS."))
                
            if any(not line.schedule_id for line in record.line_ids):
                raise ValidationError(_("All subjects must have a selected schedule before submitting."))
                
            # 1. Student Status
            if record.student_id.student_status != 'active':
                raise ValidationError(_("Student status must be active to submit a KRS."))
                
            # 2. Period Open (Only enforced for students / portal users)
            if is_portal:
                if not record.academic_year_id.krs_start_date or not record.academic_year_id.krs_end_date:
                    raise ValidationError(_("Academic year KRS period is not configured."))
                if not (record.academic_year_id.krs_start_date <= today <= record.academic_year_id.krs_end_date):
                    raise ValidationError(_("Current date is outside the allowed KRS period."))
                
            # 3. Has Advisor (Admin can bypass)
            if not record.advisor_id and not is_admin:
                raise ValidationError(_("The student must have an assigned Academic Advisor."))
                
            # 4. Max SKS Limit based on current CGPA.
            max_credits = record._get_max_credits_allowed()
            if record.total_credits > max_credits:
                raise ValidationError(
                    _("Total credits cannot exceed %(max_credits)s SKS for this student.") % {
                        'max_credits': max_credits,
                    }
                )
                
            passed_subject_ids = passed_subjects_by_student.get(record.student_id.id, set())

            # Validate Line constraints
            taken_subjects = []
            schedules = []
            
            for line in record.line_ids:
                subject = line.subject_id
                
                # 5. Subject Matches Program
                if subject.program_id and record.program_id and subject.program_id != record.program_id:
                    raise ValidationError(_("Subject '%s' does not belong to the student's program.") % subject.name)
                    
                # 6. No Duplicate Subjects
                if subject.id in taken_subjects:
                    raise ValidationError(_("Student cannot take the same subject '%s' twice in one KRS.") % subject.name)
                taken_subjects.append(subject.id)
                
                # 7. Prerequisites Met (using pre-fetched data)
                missing_prerequisites = subject.prerequisite_ids.filtered(
                    lambda prerequisite: prerequisite.id not in passed_subject_ids
                )
                if missing_prerequisites:
                    raise ValidationError(
                        _("Missing prerequisite(s) for %(subject)s: %(prerequisites)s") % {
                            'subject': subject.name,
                            'prerequisites': ', '.join(missing_prerequisites.mapped('name')),
                        }
                    )
                
                # 8. Section quota, measured on the schedule the student picked.
                # Capacity belongs to the section's room, not to the class as a
                # whole, and this KRS is excluded so the student is not counted
                # against their own seat.
                schedule = line.schedule_id
                capacity = schedule.room_capacity
                if capacity <= 0:
                    raise ValidationError(
                        _("Schedule '%s' has no room capacity set.") % schedule.display_name
                    )
                taken = schedule._enrolled_count(exclude_krs=record)
                if taken >= capacity:
                    raise ValidationError(
                        _("Class '%(name)s' is full (%(taken)s / %(capacity)s seats taken).") % {
                            'name': schedule.display_name,
                            'taken': taken,
                            'capacity': capacity,
                        }
                    )
                    
                # Collect the specific schedule selected
                if line.schedule_id:
                    sched = line.schedule_id
                    schedules.append({
                        'day': sched.day_of_week,
                        'start': sched.start_time,
                        'end': sched.end_time,
                        'name': f"{class_record.name} - {dict(sched._fields['day_of_week'].selection).get(sched.day_of_week)} {sched.start_time}-{sched.end_time}"
                    })
                    
            # 9. No Schedule Overlap
            for i, s1 in enumerate(schedules):
                for s2 in schedules[i + 1:]:
                    if s1['day'] == s2['day']:
                        if s1['start'] < s2['end'] and s1['end'] > s2['start']:
                            raise ValidationError(_("Schedule overlap detected between:\n%s\n%s") % (s1['name'], s2['name']))

    def action_submit(self):
        if any(record.state not in ('draft', 'revision') for record in self):
            raise ValidationError(_("Only draft or revision KRS records can be submitted."))
        # The nine checks run from _check_submission_requirements, triggered by
        # this write. Keeping them in the constraint means the button and a raw
        # write() are validated identically.
        self.write({'state': 'submitted'})

    def action_approve(self):
        for record in self:
            if record.state != 'submitted':
                raise ValidationError(_("Only submitted KRS records can be approved."))
            
            # Security
            user = self.env.user
            if record.advisor_id not in user.employee_ids and not user.has_group('campus_core.group_campus_administrator'):
                raise ValidationError(_("Only the assigned Academic Advisor or Academic Admin can approve this KRS."))
            # Set state to approved
            record.state = 'approved'

    def action_request_revision(self):
        for record in self:
            if record.state != 'submitted':
                raise ValidationError(_("Only submitted KRS records can be sent for revision."))
            record.state = 'revision'

    def action_reject(self):
        for record in self:
            if record.state != 'submitted':
                raise ValidationError(_("Only submitted KRS records can be rejected."))
            record.state = 'rejected'

    def action_lock(self):
        for record in self:
            if record.state != 'approved':
                raise ValidationError(_("Only approved KRS records can be locked."))
            record.state = 'locked'
            
            # Auto-generate KHS
            existing_khs = self.env['academic.khs'].search([
                ('student_id', '=', record.student_id.id),
                ('academic_year_id', '=', record.academic_year_id.id)
            ], limit=1)
            
            if not existing_khs:
                khs_lines = []
                for krs_line in record.line_ids:
                    khs_lines.append(Command.create({
                        'subject_id': krs_line.subject_id.id,
                        'credits': krs_line.credits,
                        'schedule_ids': [Command.set([krs_line.schedule_id.id])] if krs_line.schedule_id else False,
                        # grade and grade_points will be set by the lecturer later
                    }))
                    
                self.env['academic.khs'].create({
                    'student_id': record.student_id.id,
                    'academic_year_id': record.academic_year_id.id,
                    'line_ids': khs_lines,
                })
                _logger.info("Successfully generated KHS for student %s, academic year %s", record.student_id.name, record.academic_year_id.name)

    def action_unlock(self):
        """Unlock a locked KRS back to Approved state.
        Restricted to Campus Administrators only. The linked KHS is NOT deleted
        to preserve any grade data that may have already been entered.
        """
        if not self.env.user.has_group('campus_core.group_campus_administrator'):
            raise ValidationError(_(
                "Only Campus Administrators can unlock a KRS record."
            ))
        for record in self:
            if record.state != 'locked':
                raise ValidationError(_(
                    "Only locked KRS records can be unlocked. "
                    "'%(name)s' is currently '%(state)s'."
                ) % {'name': record.name, 'state': record.state})
            record.state = 'approved'


    def action_set_draft(self):
        for record in self:
            if record.state == 'locked':
                raise ValidationError(_("Locked KRS records cannot be reset to draft."))
            if record.state == 'approved' and not self.env.user.has_group('campus_core.group_campus_administrator'):
                raise ValidationError(_("Only campus administrators can reset an approved KRS to draft."))
            # A KHS outlives its KRS on purpose: action_unlock keeps it so entered
            # grades are not lost. But a KHS whose KRS has gone back to draft is an
            # orphan that still feeds the student's CGPA and still shows on the
            # transcript, with nothing left to justify it. Make the administrator
            # deal with it first rather than leaving it behind silently.
            orphan_khs = self.env['academic.khs'].sudo().search_count([
                ('student_id', '=', record.student_id.id),
                ('academic_year_id', '=', record.academic_year_id.id),
            ])
            if orphan_khs:
                raise ValidationError(_(
                    "A KHS already exists for %(student)s in %(year)s. Delete it before "
                    "returning this KRS to draft, otherwise its grades would keep "
                    "counting towards the CGPA with no study plan behind them."
                ) % {
                    'student': record.student_id.display_name,
                    'year': record.academic_year_id.display_name,
                })
            record.state = 'draft'

    @api.onchange('package_id')
    def _onchange_package_id(self):
        if self.package_id:
            if self.package_id.program_id:
                self.faculty_id = self.package_id.program_id.faculty_id
                self.program_id = self.package_id.program_id
            if self.package_id.academic_year_id:
                self.academic_year_id = self.package_id.academic_year_id
                
            # Clear existing lines and add new ones from package
            lines = [Command.clear()]
            for pkg_line in self.package_id.line_ids:
                lines.append(Command.create({
                    'subject_id': pkg_line.subject_id.id,
                }))
            self.line_ids = lines

    def _apply_package_lines(self, package):
        """Apply course package lines. Calls write() — safe to use from code."""
        self.ensure_one()
        self.write({
            'faculty_id': package.program_id.faculty_id.id,
            'program_id': package.program_id.id,
            'academic_year_id': package.academic_year_id.id,
            'line_ids': [Command.clear()] + [
                Command.create({'subject_id': line.subject_id.id})
                for line in package.line_ids
            ],
        })


class AcademicKrsLine(models.Model):
    _name = 'academic.krs.line'
    _description = 'Academic KRS Line'

    krs_id = fields.Many2one('academic.krs', string='KRS', ondelete='cascade')
    student_id = fields.Many2one(related='krs_id.student_id', string='Student', store=True)
    state = fields.Selection(related='krs_id.state', string='Status', store=True)
    schedule_id = fields.Many2one('academic.class.schedule', string='Schedule')
    class_id = fields.Many2one(related='schedule_id.class_id', store=True)
    subject_id = fields.Many2one('academic.subject', string='Subject', compute='_compute_subject_id', store=True, readonly=False)
    # Snapshot, not a live related. Depending on subject_id alone means the SKS
    # is copied when the subject is chosen and never again, so editing a
    # subject's credits later cannot rewrite study plans that were already
    # approved or locked. Explicit values in create() win over the compute, so
    # the KRS generator wizard still controls what it writes.
    credits = fields.Integer(string='Credits', compute='_compute_credits', store=True, readonly=False)

    @api.depends('schedule_id')
    def _compute_subject_id(self):
        for record in self:
            # Assigned unconditionally so clearing the schedule also clears the
            # subject it implied, instead of leaving a stale one behind.
            record.subject_id = record.schedule_id.class_id.subject_id

    @api.depends('subject_id')
    def _compute_credits(self):
        for record in self:
            if record.subject_id:
                record.credits = record.subject_id.credits

    @api.constrains('schedule_id', 'krs_id')
    def _check_schedule_academic_year(self):
        """A study plan may only hold classes offered in its own academic year."""
        for record in self:
            schedule = record.schedule_id
            if not schedule or not record.krs_id:
                continue
            if schedule.class_id.academic_year_id != record.krs_id.academic_year_id:
                raise ValidationError(_(
                    "Schedule '%(schedule)s' belongs to a different academic year "
                    "than this KRS."
                ) % {'schedule': schedule.display_name})

    @api.onchange('subject_id')
    def _onchange_subject_id(self):
        if self.subject_id and self.schedule_id and self.schedule_id.class_id.subject_id != self.subject_id:
            self.schedule_id = False

    # class_id is a stored related on schedule_id.class_id and is NULL for every
    # line created without a schedule (the package onchange and the KRS
    # generator wizard both do this). A plain UNIQUE would let those NULL rows
    # duplicate freely, so the index is restricted to rows that actually have a
    # class.
    _unique_class_per_krs = models.UniqueIndex(
        "(krs_id, class_id) WHERE class_id IS NOT NULL",
        "A class can only appear once in the same KRS.",
    )

    def _check_krs_editable(self):
        """Lines follow their KRS: once it is submitted, the content is frozen."""
        if self.filtered(lambda line: line.krs_id.state not in AcademicKrs._EDITABLE_STATES):
            raise ValidationError(_(
                "KRS subjects can only be changed while the KRS is in Draft or Needs Revision."
            ))

    @api.model_create_multi
    def create(self, vals_list):
        """Guard the third mutation path.

        write() and unlink() were already covered, but creation was not, so a
        subject could still be appended to a KRS that is submitted, approved or
        locked. That is the route by which an approved 18 SKS plan could quietly
        grow past the limit after the advisor had signed off on it.

        Checked before the insert rather than after, so the caller gets the real
        reason instead of a constraint violation.
        """
        krs_ids = {vals['krs_id'] for vals in vals_list if vals.get('krs_id')}
        if krs_ids:
            frozen = self.env['academic.krs'].browse(list(krs_ids)).filtered(
                lambda krs: krs.state not in AcademicKrs._EDITABLE_STATES
            )
            if frozen:
                raise ValidationError(_(
                    "KRS subjects can only be added while the KRS is in Draft or Needs Revision."
                ))
        return super().create(vals_list)

    def write(self, vals):
        self._check_krs_editable()
        return super().write(vals)

    def unlink(self):
        self._check_krs_editable()
        return super().unlink()
