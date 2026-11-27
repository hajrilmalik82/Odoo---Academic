from odoo import _, api, fields, models, Command
from odoo.exceptions import AccessError, UserError, ValidationError

# Unforgeable per-process sentinel: prevents JSON-RPC callers from passing a
# truthy context flag or writing `state` directly without workflow methods.
_STATE_TRANSITION_TOKEN = object()


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
        index=True,
        ondelete='restrict',
    )
    program_id = fields.Many2one(
        'academic.program',
        string='Study Program',
        compute='_compute_student_info',
        store=True,
        readonly=False,
        index=True,
        ondelete='restrict',
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
        ondelete='restrict',
        index=True,
        default=lambda self: self.env['academic.year']._get_current(),
        tracking=True,
    )

    title = fields.Char(string='Thesis Title', required=True, tracking=True)
    research_topic = fields.Text(string='Topic / Research Outline')

    supervisor_id = fields.Many2one(
        'hr.employee',
        string='Primary Supervisor',
        required=True,
        domain="[('academic_role', '=', 'lecturer'), ('program_id', '!=', False), ('program_id', '=', program_id)]",
        ondelete='restrict',
        index=True,
        tracking=True,
    )
    co_supervisor_id = fields.Many2one(
        'hr.employee',
        string='Co-Supervisor (Optional)',
        domain="[('academic_role', '=', 'lecturer'), ('id', '!=', supervisor_id)]",
        ondelete='restrict',
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
    yudisium_supervisor_by_id = fields.Many2one(
        'hr.employee', string='Yudisium Supervisor Signer', readonly=True, copy=False, ondelete='restrict',
    )
    yudisium_supervisor_date = fields.Datetime(
        string='Supervisor Yudisium Date', readonly=True, copy=False,
    )
    yudisium_advisor_approved = fields.Boolean(
        string='Yudisium: Academic Advisor Approved', readonly=True, copy=False, tracking=True,
    )
    yudisium_advisor_by_id = fields.Many2one(
        'hr.employee', string='Yudisium Advisor Signer', readonly=True, copy=False, ondelete='restrict',
    )
    yudisium_advisor_date = fields.Datetime(
        string='Advisor Yudisium Date', readonly=True, copy=False,
    )
    yudisium_dean_approved = fields.Boolean(
        string='Yudisium: Dean Approved', readonly=True, copy=False, tracking=True,
    )
    yudisium_dean_by_id = fields.Many2one(
        'hr.employee', string='Yudisium Dean Signer', readonly=True, copy=False, ondelete='restrict',
    )
    yudisium_dean_date = fields.Datetime(
        string='Dean Yudisium Date', readonly=True, copy=False,
    )

    graduation_id = fields.Many2one(
        'campus.graduation.schedule',
        string='Graduation Schedule',
        ondelete='restrict',
        index='btree_not_null',
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

    # --- Computes ---------------------------------------------------------

    @api.depends('student_id')
    def _compute_student_info(self):
        for record in self:
            record.program_id = record.student_id.program_id
            record.faculty_id = record.student_id.faculty_id

    @api.depends('student_id')
    def _compute_subject_eligibility(self):
        Partner = self.env['res.partner']
        student_ids = {
            record.student_id.id
            for record in self
            if record.student_id and isinstance(record.student_id.id, int)
        }
        passed_ids = Partner._students_passed_research_method(student_ids)
        enrolled_ids = Partner._students_enrolled_thesis_subject(student_ids)
        for record in self:
            sid = record.student_id.id if record.student_id else False
            record.research_method_passed = sid in passed_ids
            record.thesis_course_enrolled = sid in enrolled_ids

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
            record.documents_complete = (
                bool(record.yudisium_document_ids)
                and len(required_lines) == len(received_lines)
            )

    # --- Constraints & Guards ---------------------------------------------

    @api.model
    def _validate_student_eligibility(self, student, allow_graduated=False):
        """Verify that a partner is an active student with a program who passed Research Methodology."""
        if not student.exists() or not student.is_student:
            raise ValidationError(_("Only contacts marked as Student can register a thesis."))
        if not student.program_id or not student.faculty_id:
            raise ValidationError(_(
                "Student %(student)s must have a Study Program and Faculty assigned before registering a thesis."
            ) % {'student': student.display_name})
        allowed_statuses = ('active', 'graduated') if allow_graduated else ('active',)
        if student.student_status not in allowed_statuses:
            raise ValidationError(_(
                "Student %(student)s must have Active status to register or advance a thesis."
            ) % {'student': student.display_name})
        if not student._has_passed_research_method():
            raise ValidationError(_(
                "Student %(student)s cannot take a thesis yet: they must pass a "
                "Research Methodology subject in their KHS first.",
                student=student.display_name,
            ))

    @api.constrains('student_id', 'program_id', 'faculty_id')
    def _check_program_faculty_consistency(self):
        for record in self:
            if record.state == 'cancelled':
                continue
            if not record.program_id or not record.faculty_id:
                raise ValidationError(_("Thesis must specify both a Study Program and a Faculty."))
            if record.program_id.faculty_id != record.faculty_id:
                raise ValidationError(_(
                    "Study Program '%(program)s' does not belong to Faculty '%(faculty)s'.",
                    program=record.program_id.display_name,
                    faculty=record.faculty_id.display_name,
                ))
            if (
                record.state == 'draft'
                and record.student_id.program_id
                and record.program_id != record.student_id.program_id
            ):
                raise ValidationError(_(
                    "Draft thesis program must match the student's current study program."
                ))

    @api.constrains('student_id')
    def _check_student_eligible(self):
        for record in self:
            if record.state == 'cancelled':
                continue
            self._validate_student_eligibility(
                record.student_id, allow_graduated=(record.state == 'graduated'),
            )

    @api.constrains('supervisor_id', 'co_supervisor_id', 'program_id')
    def _check_supervisors_valid(self):
        for record in self:
            if record.supervisor_id:
                if not record.supervisor_id.active:
                    raise ValidationError(_(
                        "Primary Supervisor %(name)s is archived and cannot be assigned.",
                        name=record.supervisor_id.name,
                    ))
                if record.supervisor_id.academic_role != 'lecturer':
                    raise ValidationError(_(
                        "%(name)s is not a lecturer and cannot be assigned as Primary Supervisor.",
                        name=record.supervisor_id.name,
                    ))
                if record.program_id and record.supervisor_id.program_id != record.program_id:
                    raise ValidationError(_(
                        "Primary Supervisor %(name)s must belong to the student's study program (%(program)s).",
                        name=record.supervisor_id.name,
                        program=record.program_id.display_name,
                    ))
            if record.co_supervisor_id:
                if not record.co_supervisor_id.active:
                    raise ValidationError(_(
                        "Co-Supervisor %(name)s is archived and cannot be assigned.",
                        name=record.co_supervisor_id.name,
                    ))
                if record.co_supervisor_id.academic_role != 'lecturer':
                    raise ValidationError(_(
                        "%(name)s is not a lecturer and cannot be assigned as Co-Supervisor.",
                        name=record.co_supervisor_id.name,
                    ))
                if record.co_supervisor_id == record.supervisor_id:
                    raise ValidationError(_(
                        "Primary Supervisor and Co-Supervisor must be different lecturers."
                    ))

    @api.constrains('graduation_id', 'state')
    def _check_graduation_quota(self):
        for record in self:
            if not record.graduation_id or record.state == 'cancelled':
                continue
            if record.state != 'graduated':
                raise ValidationError(_(
                    "A graduation schedule can only be assigned after Yudisium is approved."
                ))
            schedule = record.graduation_id
            if schedule.state != 'open':
                raise ValidationError(_(
                    "Graduation schedule '%(name)s' is not open for assignment.",
                    name=schedule.display_name,
                ))
            schedule._lock_for_quota()
            schedule.invalidate_recordset(['participant_count'])
            if schedule.quota > 0 and schedule.participant_count > schedule.quota:
                raise ValidationError(_(
                    "Graduation schedule '%(name)s' is full (quota: %(quota)s)."
                ) % {'name': schedule.display_name, 'quota': schedule.quota})

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
        active_records = self.filtered(lambda r: r.state not in ('draft', 'cancelled'))
        if not active_records:
            return
        Partner = self.env['res.partner']
        student_ids = {r.student_id.id for r in active_records if r.student_id}
        passed_ids = Partner._students_passed_research_method(student_ids)
        thesis_stage_ids = {
            r.student_id.id
            for r in active_records
            if r.state in self._THESIS_STAGE_STATES and r.student_id
        }
        enrolled_ids = Partner._students_enrolled_thesis_subject(thesis_stage_ids)
        for record in active_records:
            allowed_statuses = ('active', 'graduated') if record.state == 'graduated' else ('active',)
            if record.student_id.student_status not in allowed_statuses:
                raise ValidationError(_(
                    "Student %(student)s must have Active status to proceed with their thesis."
                ) % {'student': record.student_id.display_name})
            if record.student_id.id not in passed_ids:
                raise ValidationError(_(
                    "Student %(student)s must pass a Research Methodology subject before "
                    "proceeding with their thesis.",
                    student=record.student_id.display_name,
                ))
            if record.state in self._THESIS_STAGE_STATES and record.student_id.id not in enrolled_ids:
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

    def _is_workflow_context(self):
        return self.env.context.get('_thesis_state_token') is _STATE_TRANSITION_TOKEN

    def _workflow_write(self, vals):
        """Execute a state or audit write authorized by a workflow action method."""
        return self.with_context(_thesis_state_token=_STATE_TRANSITION_TOKEN).write(vals)

    _WORKFLOW_APPROVAL_FIELDS = {
        'supervisor_approved',
        'co_supervisor_approved',
        'yudisium_supervisor_approved',
        'yudisium_advisor_approved',
        'yudisium_dean_approved',
    }
    _ADMIN_ONLY_FIELDS = {
        'name',
        'faculty_id',
        'program_id',
        'academic_year_id',
        'proposal_approved_date',
        'thesis_approved_date',
        'rejection_reason',
        'yudisium_supervisor_by_id',
        'yudisium_supervisor_date',
        'yudisium_advisor_by_id',
        'yudisium_advisor_date',
        'yudisium_dean_by_id',
        'yudisium_dean_date',
    }

    def _check_protected_writes(self, vals):
        if 'student_id' in vals:
            for record in self:
                if vals['student_id'] != record.student_id.id:
                    raise ValidationError(_("The student on a thesis record cannot be changed."))

        is_workflow = self._is_workflow_context()
        if self._WORKFLOW_APPROVAL_FIELDS.intersection(vals) and not self.env.su and not is_workflow:
            raise AccessError(_(
                "Approval flags can only be updated through the official approval buttons."
            ))

        is_admin = self._is_admin()
        is_staff = self.env.user.has_group('campus_core.group_campus_academic_staff')
        if not is_admin:
            if self._ADMIN_ONLY_FIELDS.intersection(vals) and not is_workflow:
                raise AccessError(_(
                    "Reference number, snapshot, academic year, and workflow audit fields cannot be modified directly."
                ))
            if 'graduation_id' in vals and not is_workflow and not is_staff:
                raise AccessError(_(
                    "Only Academic Staff or Campus Administrators can assign a graduation schedule."
                ))
            if ('supervisor_id' in vals or 'co_supervisor_id' in vals) and not is_workflow:
                if not is_staff:
                    raise AccessError(_(
                        "Only Academic Staff or Campus Administrators can reassign thesis supervisors."
                    ))
                locked = self.filtered(
                    lambda record: record.state not in ('draft', 'supervisor_rejected')
                )
                if locked:
                    raise ValidationError(_(
                        "Supervisors can only be changed while the thesis is in Draft or Supervisor Rejected."
                    ))
            if ('title' in vals or 'research_topic' in vals) and not is_workflow:
                if not is_staff:
                    raise AccessError(_(
                        "Only Academic Staff or Campus Administrators can edit thesis title or topic from the backend."
                    ))
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
        is_admin = self._is_admin()
        is_workflow = self._is_workflow_context()
        clean_list = []
        forbidden_create = (
            self._WORKFLOW_APPROVAL_FIELDS
            | (self._ADMIN_ONLY_FIELDS - {'academic_year_id', 'name', 'faculty_id', 'program_id'})
            | {'graduation_id'}
        )
        for raw_vals in vals_list:
            vals = dict(raw_vals)
            if vals.get('state') and vals['state'] != 'draft':
                raise ValidationError(_("New thesis records must start in Draft status."))
            if not is_admin and not is_workflow:
                blocked = forbidden_create.intersection(vals)
                if blocked:
                    raise AccessError(_(
                        "Protected fields (%s) cannot be set when creating a thesis."
                    ) % ', '.join(sorted(blocked)))
                if vals.get('name') and vals['name'] != 'New':
                    raise AccessError(_("Thesis numbers are assigned automatically."))
            if vals.get('student_id'):
                student = self.env['res.partner'].sudo().browse(vals['student_id'])
                self._validate_student_eligibility(student)
                if not is_admin and not is_workflow:
                    if vals.get('program_id') and vals['program_id'] != student.program_id.id:
                        raise AccessError(_("Thesis study program must match the student's program."))
                    if vals.get('faculty_id') and vals['faculty_id'] != student.faculty_id.id:
                        raise AccessError(_("Thesis faculty must match the student's faculty."))
                # Always snapshot program/faculty from the student on creation so
                # jurisdiction rules cannot be bypassed via spoofed create vals.
                if not is_admin or ('program_id' not in vals and 'faculty_id' not in vals):
                    vals['program_id'] = student.program_id.id
                    vals['faculty_id'] = student.faculty_id.id
                existing = self.sudo().search_count([
                    ('student_id', '=', vals['student_id']),
                    ('state', '!=', 'cancelled'),
                ])
                if existing:
                    raise ValidationError(_("This student already has an active thesis record."))
            if not vals.get('name') or vals.get('name') == 'New':
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('campus.thesis') or 'New'
            clean_list.append(vals)
        return super().create(clean_list)

    def copy(self, default=None):
        raise UserError(_("Thesis records cannot be duplicated."))

    def _sync_supervisor_approval_after_change(self):
        """Re-evaluate activities and auto-transition if supervisors change in supervisor_approval."""
        for record in self.filtered(lambda r: r.state == 'supervisor_approval'):
            record._close_thesis_activities(['campus_thesis.mail_activity_type_thesis_supervisor'])
            all_approved = record.supervisor_approved and (
                not record.co_supervisor_id or record.co_supervisor_approved
            )
            if all_approved:
                record._workflow_write({'state': 'proposal'})
                record.message_post(
                    body=_("All required supervisors have approved. Thesis moved to Proposal Stage."),
                )
            else:
                pending = self.env['hr.employee']
                if not record.supervisor_approved and record.supervisor_id:
                    pending |= record.supervisor_id
                if record.co_supervisor_id and not record.co_supervisor_approved:
                    pending |= record.co_supervisor_id
                if pending:
                    record._schedule_thesis_activity(
                        'campus_thesis.mail_activity_type_thesis_supervisor',
                        pending,
                        _("Review thesis supervision request from %s") % record.student_id.name,
                    )

    def write(self, vals):
        self._check_protected_writes(vals)
        is_workflow = self._is_workflow_context()
        if 'state' in vals:
            self._check_state_transition_allowed(vals['state'])
            changing = self.filtered(lambda r: r.state != vals['state'])
            if changing and not is_workflow:
                raise ValidationError(_(
                    "Thesis status cannot be changed directly; use the workflow action buttons."
                ))
        changed_sup = (
            self.filtered(lambda r: r.supervisor_id.id != vals['supervisor_id'])
            if 'supervisor_id' in vals else self.browse()
        )
        changed_cosup = (
            self.filtered(lambda r: (r.co_supervisor_id.id or False) != (vals['co_supervisor_id'] or False))
            if 'co_supervisor_id' in vals else self.browse()
        )
        res = super().write(vals)
        if not is_workflow and (changed_sup or changed_cosup):
            pre_approval_states = ('draft', 'supervisor_approval', 'supervisor_rejected')
            sup_to_reset = changed_sup.filtered(lambda r: r.state in pre_approval_states)
            cosup_to_reset = changed_cosup.filtered(lambda r: r.state in pre_approval_states)
            if sup_to_reset:
                sup_to_reset._workflow_write({'supervisor_approved': False})
            if cosup_to_reset:
                cosup_to_reset._workflow_write({'co_supervisor_approved': False})
            (sup_to_reset | cosup_to_reset)._sync_supervisor_approval_after_change()
            # If an Admin reassigns the Primary Supervisor while Step 1 Yudisium
            # approval is pending, move the pending activity to the new supervisor.
            for record in changed_sup.filtered(lambda r: r.state == 'yudisium_supervisor'):
                record._close_thesis_activities(['campus_thesis.mail_activity_type_yudisium_approval'])
                if record.supervisor_id:
                    record._schedule_thesis_activity(
                        'campus_thesis.mail_activity_type_yudisium_approval',
                        record.supervisor_id,
                        _("Yudisium Step 1: Thesis Supervisor approval for %s") % record.student_id.name,
                    )
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
            specs = Document._default_document_specs()
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
                record.sudo()._workflow_write({'yudisium_document_ids': lines})

    def _require_staff_or_admin(self, action_label):
        if not self._is_admin() and not self.env.user.has_group('campus_core.group_campus_academic_staff'):
            raise AccessError(_(
                "Only Academic Staff or Campus Administrators can %(action)s.",
                action=action_label,
            ))

    def _get_report_base_filename(self):
        self.ensure_one()
        return _('Thesis - %s') % (self.student_id.name or self.name)

    # --- Workflow Actions -------------------------------------------------

    def action_submit_supervisor(self):
        self._require_state({'draft'})
        self._require_staff_or_admin(_("submit a thesis for supervisor approval from the backend"))
        for record in self:
            if record.student_id.student_status != 'active':
                raise ValidationError(_("Student status must be active to submit a thesis."))
            if not record.student_id._has_passed_research_method():
                raise ValidationError(_(
                    "Student %(student)s must pass a Research Methodology subject before submitting.",
                    student=record.student_id.display_name,
                ))
            record._workflow_write({
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
        sup_act_type = self.env.ref(
            'campus_thesis.mail_activity_type_thesis_supervisor', raise_if_not_found=False,
        )
        for record in self:
            vals = {}
            if is_admin:
                vals['supervisor_approved'] = True
                if record.co_supervisor_id:
                    vals['co_supervisor_approved'] = True
            else:
                if record.supervisor_id.user_id == self.env.user and not record.supervisor_approved:
                    vals['supervisor_approved'] = True
                if (
                    record.co_supervisor_id
                    and record.co_supervisor_id.user_id == self.env.user
                    and not record.co_supervisor_approved
                ):
                    vals['co_supervisor_approved'] = True
                if not vals:
                    raise UserError(_("Your supervision approval has already been recorded."))

            record._workflow_write(vals)
            all_approved = record.supervisor_approved and (
                not record.co_supervisor_id or record.co_supervisor_approved
            )
            if all_approved:
                record._close_thesis_activities(['campus_thesis.mail_activity_type_thesis_supervisor'])
                record._workflow_write({'state': 'proposal'})
                record.message_post(
                    body=_("Supervisor(s) approved the supervision request. Thesis moved to Proposal Stage."),
                )
            else:
                if sup_act_type:
                    record.activity_ids.filtered(
                        lambda act: act.activity_type_id == sup_act_type and act.user_id == self.env.user
                    ).action_feedback()
                record.message_post(
                    body=_("Supervision approval recorded by %s. Waiting for the other supervisor.") % self.env.user.name,
                )

    def _open_reject_wizard(self, title, mode):
        """Open the shared rejection/return reason wizard for this thesis."""
        if len(self) != 1:
            raise UserError(_(
                "Please open a single thesis record to enter a rejection or return reason."
            ))
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
        if reason is None and not (self.env.su and self.env.context.get('_skip_reject_wizard')):
            return self._open_reject_wizard(_("Reject / Return Thesis"), 'supervisor_reject')
        cleaned = (reason or '').strip()
        if reason is not None and not cleaned:
            raise ValidationError(_("Please provide a non-empty rejection reason."))
        self._do_supervisor_reject(cleaned or _("Rejected by supervisor."))

    def _do_supervisor_reject(self, reason):
        for record in self:
            record._close_thesis_activities(['campus_thesis.mail_activity_type_thesis_supervisor'])
            record._workflow_write({
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
        is_staff = self._is_admin() or self.env.user.has_group('campus_core.group_campus_academic_staff')
        cancelled_records = self.filtered(lambda record: record.state == 'cancelled')
        if cancelled_records and not is_staff:
            raise AccessError(_(
                "Only Academic Staff or Campus Administrators can reopen a cancelled thesis."
            ))
        if not is_staff:
            self._require_actor(
                lambda record: record.supervisor_id | record.co_supervisor_id,
                _("Thesis Supervisor, Academic Staff,"),
            )
        for record in cancelled_records:
            self._validate_student_eligibility(record.student_id)
            other_active = self.sudo().search_count([
                ('student_id', '=', record.student_id.id),
                ('state', '!=', 'cancelled'),
                ('id', '!=', record.id),
            ])
            if other_active:
                raise ValidationError(_(
                    "Student %(student)s already has another active thesis record.",
                    student=record.student_id.display_name,
                ))
        self._workflow_write({
            'supervisor_approved': False,
            'co_supervisor_approved': False,
            'rejection_reason': False,
            'proposal_approved_date': False,
            'thesis_approved_date': False,
            'yudisium_supervisor_approved': False,
            'yudisium_supervisor_by_id': False,
            'yudisium_supervisor_date': False,
            'yudisium_advisor_approved': False,
            'yudisium_advisor_by_id': False,
            'yudisium_advisor_date': False,
            'yudisium_dean_approved': False,
            'yudisium_dean_by_id': False,
            'yudisium_dean_date': False,
            'graduation_id': False,
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
                record._workflow_write({
                    'proposal_approved_date': today,
                    'state': 'thesis',
                })
                record.message_post(
                    body=_("Proposal approved and Thesis course already enrolled in KRS. Advanced to Thesis Stage."),
                )
            else:
                record._workflow_write({
                    'proposal_approved_date': today,
                    'state': 'proposal_approved',
                })
                record.message_post(
                    body=_("Proposal approved. Student must enroll in a Thesis course in an approved KRS before starting the Thesis Stage."),
                )

    def action_start_thesis(self):
        self._require_state({'proposal_approved'})
        self._require_staff_or_admin(_("start the Thesis stage from the backend"))
        for record in self:
            if not record.student_id._has_enrolled_thesis_subject():
                raise ValidationError(_(
                    "Cannot start Thesis stage: %(student)s has not enrolled in a Thesis "
                    "subject in an approved or locked KRS yet.",
                    student=record.student_id.display_name,
                ))
            record._workflow_write({'state': 'thesis'})
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
            record._workflow_write({
                'thesis_approved_date': today,
                'state': 'yudisium_docs',
            })
            record.message_post(
                body=_("Thesis approved by supervisor. Proceed to Yudisium document filing."),
            )

    def action_submit_yudisium(self):
        self._require_state({'yudisium_docs'})
        self._require_staff_or_admin(_("submit Yudisium from the backend"))
        for record in self:
            if not record.documents_complete:
                raise UserError(_(
                    "All required Yudisium documents must be verified before submitting for Yudisium approval."
                ))
            record._workflow_write({'state': 'yudisium_supervisor'})
            record._schedule_thesis_activity(
                'campus_thesis.mail_activity_type_yudisium_approval',
                record.supervisor_id,
                _("Yudisium Step 1: Thesis Supervisor approval for %s") % record.student_id.name,
            )

    def _advance_yudisium_step(
        self, approved_field, by_field, date_field, get_signer,
        next_state, get_next_actor, next_summary_fn, message,
    ):
        """Record an intermediate Yudisium approval and notify the next approver."""
        now = fields.Datetime.now()
        for record in self:
            record._close_thesis_activities(['campus_thesis.mail_activity_type_yudisium_approval'])
            signer = get_signer(record)
            record._workflow_write({
                approved_field: True,
                by_field: signer.id if signer else False,
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
        step2_tpl = _("Yudisium Step 2: Academic Advisor approval for %s")
        self._advance_yudisium_step(
            'yudisium_supervisor_approved',
            'yudisium_supervisor_by_id',
            'yudisium_supervisor_date',
            lambda record: record.supervisor_id,
            'yudisium_advisor',
            lambda record: record.advisor_id,
            lambda record: step2_tpl % record.student_id.name,
            _("Yudisium Step 1 approved by Thesis Supervisor. Forwarded to Academic Advisor."),
        )

    def action_yudisium_approve_advisor(self):
        self._require_state({'yudisium_advisor'})
        self._require_actor(
            lambda record: record.advisor_id,
            _("Academic Advisor (PA)"),
        )
        step3_tpl = _("Yudisium Step 3: Dean approval for %s")
        self._advance_yudisium_step(
            'yudisium_advisor_approved',
            'yudisium_advisor_by_id',
            'yudisium_advisor_date',
            lambda record: record.advisor_id,
            'yudisium_dean',
            lambda record: record.dean_id,
            lambda record: step3_tpl % record.student_id.name,
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
            graduation = record.graduation_id or Schedule._get_nearest_schedule(lock=True)
            record._workflow_write({
                'yudisium_dean_approved': True,
                'yudisium_dean_by_id': record.dean_id.id if record.dean_id else False,
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
        if reason is None and not (self.env.su and self.env.context.get('_skip_reject_wizard')):
            return self._open_reject_wizard(_("Return Yudisium for Revision"), 'yudisium_return')
        cleaned = (reason or '').strip()
        if reason is not None and not cleaned:
            raise ValidationError(_("Please provide a non-empty return reason."))
        self._do_yudisium_return(cleaned or _("Returned for document revision."))

    def _do_yudisium_return(self, reason):
        for record in self:
            record._close_thesis_activities(['campus_thesis.mail_activity_type_yudisium_approval'])
            record._workflow_write({
                'yudisium_supervisor_approved': False,
                'yudisium_supervisor_by_id': False,
                'yudisium_supervisor_date': False,
                'yudisium_advisor_approved': False,
                'yudisium_advisor_by_id': False,
                'yudisium_advisor_date': False,
                'yudisium_dean_approved': False,
                'yudisium_dean_by_id': False,
                'yudisium_dean_date': False,
                'rejection_reason': reason,
                'state': 'yudisium_docs',
            })
            record.message_post(
                body=_("Yudisium returned to filing stage. Reason: %s") % reason,
            )

    def action_assign_nearest_graduation(self):
        self._require_state({'graduated'})
        if not self._is_admin() and not self.env.user.has_group('campus_core.group_campus_academic_staff'):
            raise AccessError(_(
                "Only Academic Staff or Campus Administrators can assign a graduation schedule."
            ))
        if self.filtered('graduation_id'):
            raise UserError(_(
                "A graduation schedule is already assigned. Update the Graduation Schedule field directly if you need to reassign it."
            ))
        Schedule = self.env['campus.graduation.schedule'].sudo()
        for record in self:
            nearest = Schedule._get_nearest_schedule(lock=True)
            if not nearest:
                raise UserError(_("No open upcoming graduation schedule is available."))
            record._workflow_write({'graduation_id': nearest.id})
            record.message_post(
                body=_("Assigned to nearest graduation schedule: %s.") % nearest.display_name,
            )

    def action_cancel(self):
        if not self._is_admin() and not self.env.user.has_group('campus_core.group_campus_academic_staff'):
            raise AccessError(_(
                "Only Academic Staff or Campus Administrators can cancel a thesis."
            ))
        if self.filtered(lambda record: record.state in ('graduated', 'cancelled')):
            raise UserError(_("Graduated or already cancelled theses cannot be cancelled."))
        self._close_thesis_activities([
            'campus_thesis.mail_activity_type_thesis_supervisor',
            'campus_thesis.mail_activity_type_yudisium_approval',
        ])
        self._workflow_write({'state': 'cancelled'})

