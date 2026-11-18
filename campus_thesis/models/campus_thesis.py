from odoo import _, api, fields, models, Command
from odoo.exceptions import AccessError, UserError, ValidationError


class CampusThesis(models.Model):
    """End-to-end student thesis (Skripsi) and Yudisium lifecycle.

    Enforces:
    1. Entry eligibility: student must have passed a Research Methodology subject
       (thesis_role='research_method') in KHS.
    2. Supervisor selection & lecturer approval/rejection workflow.
    3. Proposal stage with guidance progress logs.
    4. Thesis stage gated on enrolling in a Thesis subject (thesis_role='thesis')
       in an approved or locked KRS.
    5. Thesis completion, Yudisium document checklist, and strict sequential
       3-party approval: Thesis Supervisor -> Academic Advisor -> Dean.
    6. Automatic assignment to the nearest open Graduation (Wisuda) schedule
       and transition of student status to Graduated.
    """

    _name = 'campus.thesis'
    _description = 'Student Thesis (Skripsi)'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'campus.searchpanel.group.domain.mixin']
    _order = 'create_date desc, id desc'
    _rec_names_search = ['name', 'title', 'student_id.name', 'student_id.nim']
    _check_company_auto = True

    _unique_active_thesis_per_student = models.UniqueIndex(
        "(student_id) WHERE state != 'cancelled'",
        "A student can only have one active thesis at a time.",
    )

    name = fields.Char(
        string='Thesis Number',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: 'New',
        tracking=True,
    )
    student_id = fields.Many2one(
        'res.partner',
        string='Student',
        required=True,
        domain=[('is_student', '=', True)],
        check_company=True,
        ondelete='restrict',
        index=True,
        tracking=True,
    )
    nim = fields.Char(related='student_id.nim', string='Student ID (NIM)', readonly=True)
    # Snapshot fields matching academic.krs: historical records must preserve
    # the faculty/program at the time of thesis registration.
    faculty_id = fields.Many2one(
        'academic.faculty',
        string='Faculty',
        compute='_compute_student_info',
        store=True,
        readonly=False,
    )
    program_id = fields.Many2one(
        'academic.program',
        string='Study Program',
        compute='_compute_student_info',
        store=True,
        readonly=False,
    )
    advisor_id = fields.Many2one(
        'hr.employee',
        related='student_id.academic_advisor_id',
        string='Academic Advisor (PA)',
        readonly=True,
    )
    dean_id = fields.Many2one(
        'hr.employee',
        related='faculty_id.dean_id',
        string='Dean of Faculty',
        readonly=True,
    )
    academic_year_id = fields.Many2one(
        'academic.year',
        string='Academic Year',
        required=True,
        check_company=True,
        ondelete='restrict',
        default=lambda self: self.env['academic.year']._get_current(),
        tracking=True,
    )

    title = fields.Char(string='Thesis Title', required=True, tracking=True)
    research_topic = fields.Text(string='Topic / Research Outline')

    supervisor_id = fields.Many2one(
        'hr.employee',
        string='Primary Supervisor',
        required=True,
        domain="[('academic_role', '=', 'lecturer')]",
        check_company=True,
        index=True,
        tracking=True,
    )
    co_supervisor_id = fields.Many2one(
        'hr.employee',
        string='Co-Supervisor (Optional)',
        domain="[('academic_role', '=', 'lecturer'), ('id', '!=', supervisor_id)]",
        check_company=True,
        index=True,
        tracking=True,
    )
    supervisor_approved = fields.Boolean(
        string='Primary Supervisor Approved',
        default=False,
        copy=False,
        tracking=True,
    )
    co_supervisor_approved = fields.Boolean(
        string='Co-Supervisor Approved',
        default=False,
        copy=False,
        tracking=True,
    )
    rejection_reason = fields.Text(
        string='Rejection / Revision Reason',
        copy=False,
        tracking=True,
    )

    research_method_passed = fields.Boolean(
        string='Research Methodology Passed',
        compute='_compute_subject_eligibility',
    )
    thesis_course_enrolled = fields.Boolean(
        string='Thesis Course Taken (KRS)',
        compute='_compute_subject_eligibility',
    )

    progress_line_ids = fields.One2many(
        'campus.thesis.progress', 'thesis_id', string='Guidance & Progress Logs',
    )
    proposal_progress = fields.Float(
        string='Proposal Progress (%)',
        compute='_compute_progress_metrics',
        store=True,
        digits=(5, 2),
    )
    thesis_progress = fields.Float(
        string='Thesis Progress (%)',
        compute='_compute_progress_metrics',
        store=True,
        digits=(5, 2),
    )
    overall_progress = fields.Float(
        string='Overall Progress (%)',
        compute='_compute_progress_metrics',
        store=True,
        digits=(5, 2),
    )
    proposal_approved_date = fields.Date(
        string='Proposal Approved Date', readonly=True, copy=False, tracking=True,
    )
    thesis_approved_date = fields.Date(
        string='Thesis Approved Date', readonly=True, copy=False, tracking=True,
    )

    yudisium_document_ids = fields.One2many(
        'campus.thesis.document', 'thesis_id', string='Yudisium Documents',
    )
    required_document_count = fields.Integer(
        string='Required Documents', compute='_compute_document_progress', store=True,
    )
    received_document_count = fields.Integer(
        string='Verified Documents', compute='_compute_document_progress', store=True,
    )
    documents_complete = fields.Boolean(
        string='Documents Complete',
        compute='_compute_document_progress',
        store=True,
        tracking=True,
    )

    yudisium_supervisor_approved = fields.Boolean(
        string='Yudisium: Supervisor Approved', readonly=True, copy=False, tracking=True,
    )
    yudisium_supervisor_date = fields.Datetime(
        string='Supervisor Yudisium Date', readonly=True, copy=False,
    )
    yudisium_advisor_approved = fields.Boolean(
        string='Yudisium: Academic Advisor Approved', readonly=True, copy=False, tracking=True,
    )
    yudisium_advisor_date = fields.Datetime(
        string='Advisor Yudisium Date', readonly=True, copy=False,
    )
    yudisium_dean_approved = fields.Boolean(
        string='Yudisium: Dean Approved', readonly=True, copy=False, tracking=True,
    )
    yudisium_dean_date = fields.Datetime(
        string='Dean Yudisium Date', readonly=True, copy=False,
    )

    graduation_id = fields.Many2one(
        'campus.graduation.schedule',
        string='Graduation Schedule',
        check_company=True,
        tracking=True,
    )
    graduation_date = fields.Date(
        related='graduation_id.graduation_date',
        string='Graduation Date',
        store=True,
    )
    graduation_location = fields.Char(
        related='graduation_id.location',
        string='Graduation Location',
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('supervisor_approval', 'Supervisor Approval'),
        ('supervisor_rejected', 'Supervisor Rejected'),
        ('proposal', 'Proposal Stage'),
        ('proposal_approved', 'Proposal Approved (Needs Thesis KRS)'),
        ('thesis', 'Thesis Stage'),
        ('yudisium_docs', 'Yudisium Filing'),
        ('yudisium_supervisor', 'Yudisium: Supervisor Approval'),
        ('yudisium_advisor', 'Yudisium: Advisor Approval'),
        ('yudisium_dean', 'Yudisium: Dean Approval'),
        ('graduated', 'Yudisium Approved'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', group_expand=True, tracking=True, index=True, copy=False)

    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company,
    )

    # --- Computes ---------------------------------------------------------

    @api.depends('student_id')
    def _compute_student_info(self):
        for record in self:
            record.program_id = record.student_id.program_id
            record.faculty_id = record.student_id.faculty_id

    @api.depends('student_id')
    def _compute_subject_eligibility(self):
        for record in self:
            if not record.student_id or not isinstance(record.student_id.id, int):
                record.research_method_passed = False
                record.thesis_course_enrolled = False
                continue
            record.research_method_passed = record.student_id._has_passed_research_method()
            record.thesis_course_enrolled = record.student_id._has_enrolled_thesis_subject()

    @api.depends(
        'progress_line_ids.stage',
        'progress_line_ids.state',
        'progress_line_ids.progress_percent',
        'proposal_approved_date',
        'thesis_approved_date',
    )
    def _compute_progress_metrics(self):
        for record in self:
            if record.proposal_approved_date:
                proposal_pct = 100.0
            else:
                approved_proposal = record.progress_line_ids.filtered(
                    lambda log: log.stage == 'proposal' and log.state == 'approved'
                )
                proposal_pct = max(approved_proposal.mapped('progress_percent'), default=0.0)

            if record.thesis_approved_date:
                thesis_pct = 100.0
            else:
                approved_thesis = record.progress_line_ids.filtered(
                    lambda log: log.stage == 'thesis' and log.state == 'approved'
                )
                thesis_pct = max(approved_thesis.mapped('progress_percent'), default=0.0)

            record.proposal_progress = proposal_pct
            record.thesis_progress = thesis_pct
            record.overall_progress = round((proposal_pct + thesis_pct) / 2.0, 2)

    @api.depends('yudisium_document_ids.required', 'yudisium_document_ids.received')
    def _compute_document_progress(self):
        for record in self:
            required_lines = record.yudisium_document_ids.filtered('required')
            received_lines = required_lines.filtered('received')
            record.required_document_count = len(required_lines)
            record.received_document_count = len(received_lines)
            record.documents_complete = bool(required_lines) and len(required_lines) == len(received_lines)

    # --- Constraints & Guards ---------------------------------------------

    @api.model
    def _validate_student_eligibility(self, student):
        """Verify that a partner is a student who passed Research Methodology."""
        if not student.exists() or not student.is_student:
            raise ValidationError(_("Only contacts marked as Student can register a thesis."))
        if not student._has_passed_research_method():
            raise ValidationError(_(
                "Student %(student)s cannot take a thesis yet: they must pass a "
                "Research Methodology subject in their KHS first.",
                student=student.display_name,
            ))

    @api.constrains('student_id')
    def _check_student_eligible(self):
        for record in self:
            self._validate_student_eligibility(record.student_id)

    @api.constrains('supervisor_id', 'co_supervisor_id')
    def _check_supervisors_valid(self):
        for record in self:
            if record.supervisor_id and record.supervisor_id.academic_role != 'lecturer':
                raise ValidationError(_(
                    "%(name)s is not a lecturer and cannot be assigned as Primary Supervisor.",
                    name=record.supervisor_id.name,
                ))
            if record.co_supervisor_id:
                if record.co_supervisor_id.academic_role != 'lecturer':
                    raise ValidationError(_(
                        "%(name)s is not a lecturer and cannot be assigned as Co-Supervisor.",
                        name=record.co_supervisor_id.name,
                    ))
                if record.co_supervisor_id == record.supervisor_id:
                    raise ValidationError(_(
                        "Primary Supervisor and Co-Supervisor must be different lecturers."
                    ))

    _STATE_TRANSITIONS = {
        'draft': {'supervisor_approval', 'cancelled'},
        'supervisor_approval': {'proposal', 'supervisor_rejected', 'cancelled'},
        'supervisor_rejected': {'draft', 'cancelled'},
        'proposal': {'proposal_approved', 'thesis', 'supervisor_rejected', 'cancelled'},
        'proposal_approved': {'thesis', 'cancelled'},
        'thesis': {'yudisium_docs', 'cancelled'},
        'yudisium_docs': {'yudisium_supervisor', 'cancelled'},
        'yudisium_supervisor': {'yudisium_advisor', 'yudisium_docs', 'cancelled'},
        'yudisium_advisor': {'yudisium_dean', 'yudisium_docs', 'cancelled'},
        'yudisium_dean': {'graduated', 'yudisium_docs', 'cancelled'},
        'graduated': set(),
        'cancelled': {'draft'},
    }

    _THESIS_STAGE_STATES = {
        'thesis',
        'yudisium_docs',
        'yudisium_supervisor',
        'yudisium_advisor',
        'yudisium_dean',
        'graduated',
    }
    _YUDISIUM_APPROVAL_STATES = {
        'yudisium_supervisor',
        'yudisium_advisor',
        'yudisium_dean',
        'graduated',
    }

    @api.constrains('state')
    def _check_state_prerequisites(self):
        """Enforce business invariants regardless of how state is written."""
        for record in self:
            if record.state in ('draft', 'cancelled'):
                continue
            if not record.student_id._has_passed_research_method():
                raise ValidationError(_(
                    "Student %(student)s must pass a Research Methodology subject before "
                    "proceeding with their thesis.",
                    student=record.student_id.display_name,
                ))
            if record.state in self._THESIS_STAGE_STATES and not record.student_id._has_enrolled_thesis_subject():
                raise ValidationError(_(
                    "Student %(student)s must enroll in a Thesis subject in an approved "
                    "or locked KRS before entering the Thesis stage.",
                    student=record.student_id.display_name,
                ))
            if record.state in self._YUDISIUM_APPROVAL_STATES and not record.documents_complete:
                raise ValidationError(_(
                    "All required Yudisium documents must be verified before submitting "
                    "for Yudisium approval."
                ))
            if record.state == 'yudisium_advisor' and not record.yudisium_supervisor_approved:
                raise ValidationError(_(
                    "Thesis Supervisor must approve Yudisium before Academic Advisor approval."
                ))
            if record.state == 'yudisium_dean' and not (
                record.yudisium_supervisor_approved and record.yudisium_advisor_approved
            ):
                raise ValidationError(_(
                    "Thesis Supervisor and Academic Advisor must both approve Yudisium "
                    "before Dean approval."
                ))
            if record.state == 'graduated' and not (
                record.yudisium_supervisor_approved
                and record.yudisium_advisor_approved
                and record.yudisium_dean_approved
            ):
                raise ValidationError(_(
                    "Supervisor, Academic Advisor, and Dean must all approve Yudisium "
                    "before graduation."
                ))

    def _check_state_transition_allowed(self, new_state):
        for record in self:
            if record.state == new_state:
                continue
            if new_state not in self._STATE_TRANSITIONS.get(record.state, set()):
                raise ValidationError(_(
                    "Invalid thesis status change from '%(old)s' to '%(new)s'.",
                    old=record.state,
                    new=new_state,
                ))

    def _check_protected_writes(self, vals):
        if 'student_id' in vals:
            for record in self:
                if vals['student_id'] != record.student_id.id:
                    raise ValidationError(_("The student on a thesis record cannot be changed."))

        workflow_fields = {
            'supervisor_approved',
            'co_supervisor_approved',
            'yudisium_supervisor_approved',
            'yudisium_advisor_approved',
            'yudisium_dean_approved',
        }
        if (
            workflow_fields.intersection(vals)
            and not self.env.su
            and not self.env.context.get('_thesis_workflow_action')
        ):
            raise AccessError(_(
                "Approval flags can only be updated through the official approval buttons."
            ))

        is_admin = self._is_admin()
        if not is_admin:
            if 'supervisor_id' in vals or 'co_supervisor_id' in vals:
                locked = self.filtered(
                    lambda record: record.state not in ('draft', 'supervisor_rejected')
                )
                if locked:
                    raise ValidationError(_(
                        "Supervisors can only be changed while the thesis is in Draft or Supervisor Rejected."
                    ))
            if 'title' in vals or 'research_topic' in vals:
                locked_titles = self.filtered(
                    lambda record: record.state not in ('draft', 'supervisor_rejected', 'proposal')
                )
                if locked_titles:
                    raise ValidationError(_(
                        "Thesis title and topic cannot be changed after proposal approval."
                    ))

    @api.model_create_multi
    def create(self, vals_list):
        self.check_access('create')
        for vals in vals_list:
            if vals.get('state') and vals['state'] != 'draft':
                raise ValidationError(_("New thesis records must start in Draft status."))
            if vals.get('student_id'):
                student = self.env['res.partner'].sudo().browse(vals['student_id'])
                self._validate_student_eligibility(student)
                existing = self.sudo().search_count([
                    ('student_id', '=', vals['student_id']),
                    ('state', '!=', 'cancelled'),
                ])
                if existing:
                    raise ValidationError(_("This student already has an active thesis record."))
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('campus.thesis') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        self._check_protected_writes(vals)
        if 'state' in vals:
            self._check_state_transition_allowed(vals['state'])
        changed_sup = (
            'supervisor_id' in vals
            and self.filtered(lambda r: r.supervisor_id.id != vals['supervisor_id'])
        )
        changed_cosup = (
            'co_supervisor_id' in vals
            and self.filtered(lambda r: (r.co_supervisor_id.id or False) != (vals['co_supervisor_id'] or False))
        )
        res = super().write(vals)
        if changed_sup and not self.env.context.get('_thesis_workflow_action'):
            changed_sup.with_context(_thesis_workflow_action=True).write({'supervisor_approved': False})
        if changed_cosup and not self.env.context.get('_thesis_workflow_action'):
            changed_cosup.with_context(_thesis_workflow_action=True).write({'co_supervisor_approved': False})
        return res

    def unlink(self):
        protected = self.filtered(
            lambda record: record.state not in ('draft', 'supervisor_rejected', 'cancelled')
        )
        if protected:
            raise ValidationError(_(
                "Active or graduated thesis records cannot be deleted. Cancel them instead."
            ))
        return super().unlink()

    # --- Role & Activity Helpers ------------------------------------------

    def _is_admin(self):
        return self.env.su or self.env.user.has_group('campus_core.group_campus_administrator')

    def _require_state(self, allowed_states):
        wrong = self.filtered(lambda record: record.state not in allowed_states)
        if wrong:
            raise UserError(_(
                "This action is not allowed from the current thesis status."
            ))

    def _require_actor(self, get_employees, role_label):
        if self._is_admin():
            return
        for record in self:
            allowed_users = get_employees(record).mapped('user_id')
            if self.env.user not in allowed_users:
                raise AccessError(_(
                    "Only the assigned %(role)s or a Campus Administrator may perform this action.",
                    role=role_label,
                ))

    def _schedule_thesis_activity(self, xmlid, employees, summary):
        self.ensure_one()
        activity_type = self.env.ref(xmlid, raise_if_not_found=False)
        if not activity_type:
            return
        for user in employees.mapped('user_id'):
            self.activity_schedule(xmlid, user_id=user.id, summary=summary)

    def _close_thesis_activities(self, xmlids):
        for xmlid in xmlids:
            self.activity_feedback([xmlid])

    def _ensure_default_documents(self):
        Document = self.env['campus.thesis.document']
        for record in self:
            specs = Document._default_document_specs(company=record.company_id)
            existing_types = set(record.yudisium_document_ids.mapped('document_type'))
            lines = [
                Command.create({
                    'document_type': doc_type,
                    'required': required,
                })
                for doc_type, required in specs
                if doc_type not in existing_types
            ]
            if lines:
                record.sudo().write({'yudisium_document_ids': lines})

    def _get_report_base_filename(self):
        self.ensure_one()
        return 'Thesis - %s' % (self.student_id.name or self.name)

    # --- Workflow Actions -------------------------------------------------

    def action_submit_supervisor(self):
        self._require_state({'draft'})
        for record in self:
            if record.student_id.student_status != 'active':
                raise ValidationError(_("Student status must be active to submit a thesis."))
            if not record.student_id._has_passed_research_method():
                raise ValidationError(_(
                    "Student %(student)s must pass a Research Methodology subject before submitting.",
                    student=record.student_id.display_name,
                ))
            record.with_context(_thesis_workflow_action=True).write({
                'supervisor_approved': False,
                'co_supervisor_approved': False,
                'rejection_reason': False,
                'state': 'supervisor_approval',
            })
            supervisors = record.supervisor_id | record.co_supervisor_id
            record._schedule_thesis_activity(
                'campus_thesis.mail_activity_type_thesis_supervisor',
                supervisors,
                _("Review thesis supervision request from %s") % record.student_id.name,
            )

    def action_supervisor_approve(self):
        self._require_state({'supervisor_approval'})
        self._require_actor(
            lambda record: record.supervisor_id | record.co_supervisor_id,
            _("Thesis Supervisor"),
        )
        is_admin = self._is_admin()
        for record in self:
            vals = {}
            if is_admin:
                vals['supervisor_approved'] = True
                if record.co_supervisor_id:
                    vals['co_supervisor_approved'] = True
            else:
                if record.supervisor_id.user_id == self.env.user:
                    vals['supervisor_approved'] = True
                if record.co_supervisor_id and record.co_supervisor_id.user_id == self.env.user:
                    vals['co_supervisor_approved'] = True

            record.with_context(_thesis_workflow_action=True).write(vals)
            all_approved = record.supervisor_approved and (
                not record.co_supervisor_id or record.co_supervisor_approved
            )
            if all_approved:
                record._close_thesis_activities(['campus_thesis.mail_activity_type_thesis_supervisor'])
                record.write({'state': 'proposal'})
                record.message_post(
                    body=_("Supervisor(s) approved the supervision request. Thesis moved to Proposal Stage."),
                )
            else:
                record.message_post(
                    body=_("Supervision approval recorded by %s. Waiting for the other supervisor.") % self.env.user.name,
                )

    def _open_reject_wizard(self, title, mode):
        """Open the shared rejection/return reason wizard for this thesis."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': 'campus.thesis.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_thesis_id': self.id,
                'default_mode': mode,
            },
        }

    def action_supervisor_reject(self, reason=None):
        self._require_state({'supervisor_approval', 'proposal'})
        self._require_actor(
            lambda record: record.supervisor_id | record.co_supervisor_id,
            _("Thesis Supervisor"),
        )
        if not reason and not self.env.context.get('_skip_reject_wizard'):
            return self._open_reject_wizard(_("Reject / Return Thesis"), 'supervisor_reject')
        self._do_supervisor_reject(reason or _("Rejected by supervisor."))

    def _do_supervisor_reject(self, reason):
        for record in self:
            record._close_thesis_activities(['campus_thesis.mail_activity_type_thesis_supervisor'])
            record.with_context(_thesis_workflow_action=True).write({
                'supervisor_approved': False,
                'co_supervisor_approved': False,
                'rejection_reason': reason,
                'state': 'supervisor_rejected',
            })
            record.message_post(
                body=_("Thesis rejected by supervisor. Reason: %s") % reason,
            )

    def action_reset_to_draft(self):
        self._require_state({'supervisor_rejected', 'cancelled'})
        self.with_context(_thesis_workflow_action=True).write({
            'supervisor_approved': False,
            'co_supervisor_approved': False,
            'proposal_approved_date': False,
            'thesis_approved_date': False,
            'yudisium_supervisor_approved': False,
            'yudisium_supervisor_date': False,
            'yudisium_advisor_approved': False,
            'yudisium_advisor_date': False,
            'yudisium_dean_approved': False,
            'yudisium_dean_date': False,
            'state': 'draft',
        })

    def action_approve_proposal(self):
        self._require_state({'proposal'})
        self._require_actor(
            lambda record: record.supervisor_id,
            _("Primary Thesis Supervisor"),
        )
        today = fields.Date.context_today(self)
        for record in self:
            if record.student_id._has_enrolled_thesis_subject():
                record.write({
                    'proposal_approved_date': today,
                    'state': 'thesis',
                })
                record.message_post(
                    body=_("Proposal approved and Thesis course already enrolled in KRS. Advanced to Thesis Stage."),
                )
            else:
                record.write({
                    'proposal_approved_date': today,
                    'state': 'proposal_approved',
                })
                record.message_post(
                    body=_("Proposal approved. Student must enroll in a Thesis course in an approved KRS before starting the Thesis Stage."),
                )

    def action_start_thesis(self):
        self._require_state({'proposal_approved'})
        for record in self:
            if not record.student_id._has_enrolled_thesis_subject():
                raise ValidationError(_(
                    "Cannot start Thesis stage: %(student)s has not enrolled in a Thesis "
                    "subject in an approved or locked KRS yet.",
                    student=record.student_id.display_name,
                ))
            record.write({'state': 'thesis'})
            record.message_post(body=_("Thesis course KRS verified. Advanced to Thesis Stage."))

    def action_approve_thesis(self):
        self._require_state({'thesis'})
        self._require_actor(
            lambda record: record.supervisor_id,
            _("Primary Thesis Supervisor"),
        )
        today = fields.Date.context_today(self)
        for record in self:
            record._ensure_default_documents()
            record.write({
                'thesis_approved_date': today,
                'state': 'yudisium_docs',
            })
            record.message_post(
                body=_("Thesis approved by supervisor. Proceed to Yudisium document filing."),
            )

    def action_submit_yudisium(self):
        self._require_state({'yudisium_docs'})
        for record in self:
            record._ensure_default_documents()
            if not record.documents_complete:
                raise UserError(_(
                    "All required Yudisium documents must be verified before submitting for Yudisium approval."
                ))
            record.write({'state': 'yudisium_supervisor'})
            record._schedule_thesis_activity(
                'campus_thesis.mail_activity_type_yudisium_approval',
                record.supervisor_id,
                _("Yudisium Step 1: Thesis Supervisor approval for %s") % record.student_id.name,
            )

    def _advance_yudisium_step(
        self, approved_field, date_field, next_state, get_next_actor, next_summary_fn, message,
    ):
        """Record an intermediate Yudisium approval and notify the next approver."""
        now = fields.Datetime.now()
        for record in self:
            record._close_thesis_activities(['campus_thesis.mail_activity_type_yudisium_approval'])
            record.with_context(_thesis_workflow_action=True).write({
                approved_field: True,
                date_field: now,
                'state': next_state,
            })
            next_actor = get_next_actor(record)
            if next_actor:
                record._schedule_thesis_activity(
                    'campus_thesis.mail_activity_type_yudisium_approval',
                    next_actor,
                    next_summary_fn(record),
                )
            record.message_post(body=message)

    def action_yudisium_approve_supervisor(self):
        self._require_state({'yudisium_supervisor'})
        self._require_actor(
            lambda record: record.supervisor_id,
            _("Primary Thesis Supervisor"),
        )
        self._advance_yudisium_step(
            'yudisium_supervisor_approved',
            'yudisium_supervisor_date',
            'yudisium_advisor',
            lambda record: record.advisor_id,
            lambda record: _("Yudisium Step 2: Academic Advisor approval for %s") % record.student_id.name,
            _("Yudisium Step 1 approved by Thesis Supervisor. Forwarded to Academic Advisor."),
        )

    def action_yudisium_approve_advisor(self):
        self._require_state({'yudisium_advisor'})
        self._require_actor(
            lambda record: record.advisor_id,
            _("Academic Advisor (PA)"),
        )
        self._advance_yudisium_step(
            'yudisium_advisor_approved',
            'yudisium_advisor_date',
            'yudisium_dean',
            lambda record: record.dean_id,
            lambda record: _("Yudisium Step 3: Dean approval for %s") % record.student_id.name,
            _("Yudisium Step 2 approved by Academic Advisor. Forwarded to Dean of Faculty."),
        )

    def action_yudisium_approve_dean(self):
        self._require_state({'yudisium_dean'})
        self._require_actor(
            lambda record: record.dean_id,
            _("Dean of Faculty"),
        )
        now = fields.Datetime.now()
        Schedule = self.env['campus.graduation.schedule'].sudo()
        for record in self:
            record._close_thesis_activities(['campus_thesis.mail_activity_type_yudisium_approval'])
            graduation = record.graduation_id or Schedule._get_nearest_schedule(company=record.company_id)
            record.with_context(_thesis_workflow_action=True).write({
                'yudisium_dean_approved': True,
                'yudisium_dean_date': now,
                'graduation_id': graduation.id if graduation else False,
                'state': 'graduated',
            })
            record.student_id.sudo().write({'student_status': 'graduated'})
            grad_msg = (
                _("Assigned to nearest graduation schedule: %s.") % graduation.display_name
                if graduation
                else _("No upcoming open graduation schedule found yet; assign once scheduled.")
            )
            record.message_post(
                body=_("Yudisium Step 3 approved by Dean! Student status set to Graduated. %s") % grad_msg,
            )

    def action_yudisium_return_to_docs(self, reason=None):
        self._require_state({'yudisium_supervisor', 'yudisium_advisor', 'yudisium_dean'})
        if not self._is_admin():
            for record in self:
                if record.state == 'yudisium_supervisor':
                    expected = record.supervisor_id
                    label = _("Primary Thesis Supervisor")
                elif record.state == 'yudisium_advisor':
                    expected = record.advisor_id
                    label = _("Academic Advisor (PA)")
                else:
                    expected = record.dean_id
                    label = _("Dean of Faculty")
                if self.env.user not in expected.mapped('user_id'):
                    raise AccessError(_(
                        "Only the assigned %(role)s or a Campus Administrator may return this Yudisium.",
                        role=label,
                    ))
        if not reason and not self.env.context.get('_skip_reject_wizard'):
            return self._open_reject_wizard(_("Return Yudisium for Revision"), 'yudisium_return')
        self._do_yudisium_return(reason or _("Returned for document revision."))

    def _do_yudisium_return(self, reason):
        for record in self:
            record._close_thesis_activities(['campus_thesis.mail_activity_type_yudisium_approval'])
            record.with_context(_thesis_workflow_action=True).write({
                'yudisium_supervisor_approved': False,
                'yudisium_supervisor_date': False,
                'yudisium_advisor_approved': False,
                'yudisium_advisor_date': False,
                'yudisium_dean_approved': False,
                'yudisium_dean_date': False,
                'rejection_reason': reason,
                'state': 'yudisium_docs',
            })
            record.message_post(
                body=_("Yudisium returned to filing stage. Reason: %s") % reason,
            )

    def action_assign_nearest_graduation(self):
        self._require_state({'graduated'})
        Schedule = self.env['campus.graduation.schedule'].sudo()
        for record in self:
            nearest = Schedule._get_nearest_schedule(company=record.company_id)
            if not nearest:
                raise UserError(_("No open upcoming graduation schedule is available."))
            record.graduation_id = nearest.id

    def action_cancel(self):
        if self.filtered(lambda record: record.state in ('graduated', 'cancelled')):
            raise UserError(_("Graduated or already cancelled theses cannot be cancelled."))
        self._close_thesis_activities([
            'campus_thesis.mail_activity_type_thesis_supervisor',
            'campus_thesis.mail_activity_type_yudisium_approval',
        ])
        self.write({'state': 'cancelled'})

