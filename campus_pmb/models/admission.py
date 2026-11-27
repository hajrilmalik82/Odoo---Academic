import logging
import re
import secrets
import zlib

from psycopg2 import IntegrityError

from odoo import _, api, fields, models, Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import SQL, float_compare

_logger = logging.getLogger(__name__)
# Unforgeable per-process sentinel: prevents JSON-RPC callers from passing a
# truthy context flag to bypass action_accept() / action_register() via write().
_STATE_TRANSITION_TOKEN = object()
_PG_INT4_MAX = 2147483647
_NIM_LOCK_CLASSID = 0x43504D42  # 'CPMB' namespace for pg_advisory_xact_lock


def _escape_like(value):
    """Escape LIKE/ILIKE wildcards for exact case-insensitive matches."""
    return (value or '').replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


class CampusAdmission(models.Model):
    _name = 'campus.admission'
    _description = 'New Student Admission'
    _order = 'registration_date desc, id desc'
    # campus.searchpanel.group.domain.mixin carries the Odoo 19 search-panel
    # workaround this model's faculty-grouped program_id panel needs; it used to
    # be a verbatim copy of the one in academic.subject.
    _inherit = ['mail.thread', 'mail.activity.mixin', 'campus.searchpanel.group.domain.mixin']

    @api.model
    def _admission_path_selection(self):
        """One definition, shared with campus.admission.requirement."""
        return [
            ('regular', _('Regular')),
            ('scholarship', _('Scholarship')),
            ('transfer', _('Transfer')),
        ]

    registration_number = fields.Char(
        string='Registration Number',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: 'New',
        tracking=True,
    )
    name = fields.Char(string='Applicant Name', required=True, tracking=True)
    email = fields.Char(string='Email', required=True, tracking=True)
    phone = fields.Char(string='Phone', tracking=True)
    previous_school = fields.Char(string='Previous School', tracking=True)
    admission_path = fields.Selection(
        selection=lambda self: self._admission_path_selection(),
        string='Admission Path', default='regular', required=True, tracking=True,
    )

    registration_date = fields.Date(
        string='Registration Date', default=fields.Date.context_today, tracking=True
    )
    faculty_id = fields.Many2one(
        'academic.faculty', string='Faculty', required=True, tracking=True, index=True,
    )
    program_id = fields.Many2one(
        'academic.program', string='Program', required=True, tracking=True,
        domain="[('faculty_id', '=', faculty_id)]", index=True,
    )
    academic_year_id = fields.Many2one(
        'academic.year', string='Academic Year', required=True, tracking=True, index=True,
    )

    partner_id = fields.Many2one(
        'res.partner', string='Student Profile', readonly=True, tracking=True, copy=False,
        index='btree_not_null',
    )
    user_id = fields.Many2one(
        'res.users', string='Portal User', readonly=True, tracking=True, copy=False,
        index='btree_not_null',
    )

    @api.onchange('faculty_id')
    def _onchange_faculty_id_clear_program(self):
        if self.program_id and self.program_id.faculty_id != self.faculty_id:
            self.program_id = False

    @api.constrains('faculty_id', 'program_id')
    def _check_program_belongs_to_faculty(self):
        for record in self:
            if (
                record.program_id
                and record.faculty_id
                and record.program_id.faculty_id != record.faculty_id
            ):
                raise ValidationError(_(
                    "Program '%(program)s' does not belong to Faculty '%(faculty)s'."
                ) % {
                    'program': record.program_id.display_name,
                    'faculty': record.faculty_id.display_name,
                })

    @api.constrains('email')
    def _check_email_format(self):
        for record in self:
            if record.email and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', record.email.strip()):
                raise ValidationError(_("Invalid email address format: %(email)s") % {'email': record.email})

    @api.constrains('phone')
    def _check_phone(self):
        for record in self:
            if not record.phone:
                continue
            cleaned = re.sub(r'[\s\-\(\)\.]', '', record.phone)
            if not re.match(r'^\+?[0-9]{8,15}$', cleaned):
                raise ValidationError(_("Invalid phone number format: %(phone)s") % {'phone': record.phone})

    document_line_ids = fields.One2many(
        'campus.admission.document', 'admission_id', string='Document Checklist'
    )
    # All three share one compute and one @api.depends, so they share one
    # storage decision too. Odoo warns at registry build time when a compute
    # method feeds both stored and non-stored fields, because reading the
    # non-stored one then silently recomputes and rewrites the stored one.
    required_document_count = fields.Integer(
        string='Required Documents', compute='_compute_document_progress', store=True,
    )
    received_document_count = fields.Integer(
        string='Received Documents', compute='_compute_document_progress', store=True,
    )
    # store=True because the field is tracked: without it the value is computed
    # on read and mail.thread only logs a change when the record itself is
    # written, so ticking the last checklist line from the document list left no
    # trace while ticking it from the admission form did. The @api.depends
    # already covers both write paths.
    documents_complete = fields.Boolean(
        string='Documents Complete', compute='_compute_document_progress',
        store=True, tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency', compute='_compute_currency_id',
        default=lambda self: self.env.company.currency_id,
    )

    def _compute_currency_id(self):
        default_currency = self.env.company.currency_id
        for record in self:
            record.currency_id = default_currency

    registration_fee = fields.Monetary(
        string='Registration Fee', compute='_compute_fees', store=True,
        readonly=False, currency_field='currency_id', tracking=True,
    )
    registration_fee_paid = fields.Boolean(
        string='Registration Fee Paid', tracking=True, copy=False,
    )
    reregistration_fee = fields.Monetary(
        string='Re-registration Fee', compute='_compute_fees', store=True,
        readonly=False, currency_field='currency_id', tracking=True,
    )
    reregistration_fee_paid = fields.Boolean(
        string='Re-registration Fee Paid', tracking=True, copy=False,
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('document_review', 'Document Review'),
        ('accepted', 'Accepted'),
        ('registered', 'Registered'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', tracking=True, index=True, copy=False)

    _unique_registration_number = models.UniqueIndex(
        "(registration_number) WHERE registration_number <> 'New'",
        "Admission registration number must be unique.",
    )
    _email_year_unique = models.UniqueIndex(
        "(lower(email), academic_year_id)",
        "An admission record already exists for this email in this academic year.",
    )

    @api.constrains('registration_fee', 'reregistration_fee')
    def _check_non_negative_fees(self):
        for record in self:
            if record.registration_fee < 0 or record.reregistration_fee < 0:
                raise ValidationError(_("Admission fees cannot be negative."))

    _SYSTEM_MANAGED_FIELDS = frozenset(('partner_id', 'user_id', 'registration_number'))

    @api.model
    def _expected_configured_fees(self, admission_path, program):
        """Return (registration_fee, reregistration_fee) from campus.admission.fee rules."""
        Fee = self.env['campus.admission.fee']
        fee_index = Fee._build_fee_index()
        return (
            Fee._lookup_fee_from_index(fee_index, 'registration', admission_path, program),
            Fee._lookup_fee_from_index(fee_index, 'reregistration', admission_path, program),
        )

    @api.model_create_multi
    def create(self, vals_list):
        is_admin = self.env.su or self.env.user.has_group('campus_core.group_campus_administrator')
        Program = self.env['academic.program'].sudo()
        cleaned = []
        for raw_vals in vals_list:
            vals = dict(raw_vals)
            if vals.get('email'):
                vals['email'] = str(vals['email']).strip().lower()
            if not is_admin and ('partner_id' in vals or 'user_id' in vals):
                raise AccessError(_("Student profile and portal user links are managed automatically upon registration."))
            if not is_admin and ('registration_fee' in vals or 'reregistration_fee' in vals):
                path = vals.get('admission_path') or 'regular'
                program = Program.browse(vals['program_id']) if vals.get('program_id') else Program.browse()
                exp_reg, exp_rereg = self._expected_configured_fees(path, program)
                if 'registration_fee' in vals and float_compare(vals['registration_fee'] or 0.0, exp_reg, precision_digits=2) != 0:
                    raise AccessError(_("Only Campus Administrators can manually override configured admission fees."))
                if 'reregistration_fee' in vals and float_compare(vals['reregistration_fee'] or 0.0, exp_rereg, precision_digits=2) != 0:
                    raise AccessError(_("Only Campus Administrators can manually override configured admission fees."))
            if not vals.get('registration_number') or vals.get('registration_number') == 'New':
                vals['registration_number'] = (
                    self.env['ir.sequence'].sudo().next_by_code('campus.admission') or 'New'
                )
            elif not is_admin:
                raise AccessError(_("Registration numbers are assigned automatically."))
            if vals.get('state') and vals['state'] != 'draft':
                raise ValidationError(_("New admissions must start in draft status."))
            cleaned.append(vals)
        # The checklist goes into the same insert, with specs cached per path across the batch.
        Document = self.env['campus.admission.document']
        specs_by_path = {}
        custom_doc_indices = []
        for idx, vals in enumerate(cleaned):
            if not vals.get('document_line_ids'):
                path = vals.get('admission_path', 'regular')
                if path not in specs_by_path:
                    specs_by_path[path] = Document._default_document_specs(path)
                vals['document_line_ids'] = [
                    Command.create({'document_type': document_type, 'required': required})
                    for document_type, required in specs_by_path[path]
                ]
            else:
                custom_doc_indices.append(idx)
        records = super().create(cleaned)
        if custom_doc_indices:
            records.browse([records[idx].id for idx in custom_doc_indices])._ensure_default_documents()
        return records

    def copy(self, default=None):
        raise UserError(_(
            "Admission records cannot be duplicated. Create a new application for the applicant instead."
        ))

    @api.depends('document_line_ids.required', 'document_line_ids.received')
    def _compute_document_progress(self):
        for record in self:
            required_lines = record.document_line_ids.filtered('required')
            received_lines = required_lines.filtered('received')
            record.required_document_count = len(required_lines)
            record.received_document_count = len(received_lines)
            record.documents_complete = bool(record.document_line_ids) and len(required_lines) == len(received_lines)

    @api.depends('admission_path', 'program_id')
    def _compute_fees(self):
        Fee = self.env['campus.admission.fee']
        fee_index = Fee._build_fee_index()
        for record in self:
            if record.state in ('accepted', 'registered', 'rejected'):
                # Preserve historical fees once acceptance/decision is finalized.
                continue
            record.registration_fee = Fee._lookup_fee_from_index(
                fee_index, 'registration', record.admission_path, record.program_id,
            )
            record.reregistration_fee = Fee._lookup_fee_from_index(
                fee_index, 'reregistration', record.admission_path, record.program_id,
            )

    def _ensure_default_documents(self, prune_unreceived=False):
        Document = self.env['campus.admission.document']
        specs_by_path = {}
        for record in self:
            path = record.admission_path
            if path not in specs_by_path:
                specs_by_path[path] = Document._default_document_specs(path)
            default_specs = specs_by_path[path]
            spec_map = dict(default_specs)
            existing_by_type = {line.document_type: line for line in record.document_line_ids}
            commands = []
            for doc_type, required in default_specs:
                if doc_type not in existing_by_type:
                    commands.append(Command.create({
                        'document_type': doc_type,
                        'required': required,
                    }))
                elif prune_unreceived and existing_by_type[doc_type].required != required:
                    commands.append(Command.update(
                        existing_by_type[doc_type].id, {'required': required},
                    ))
            if prune_unreceived:
                for doc_type, line in existing_by_type.items():
                    if doc_type not in spec_map and not line.received:
                        commands.append(Command.delete(line.id))
            if commands:
                record.with_context(_pmb_state_token=_STATE_TRANSITION_TOKEN).write({
                    'document_line_ids': commands,
                })

    _STATE_TRANSITIONS = {
        'draft': {'submitted', 'rejected'},
        'submitted': {'document_review', 'rejected'},
        'document_review': {'accepted', 'rejected'},
        'accepted': {'registered', 'rejected'},
        'registered': set(),
        'rejected': set(),
    }

    def _check_state_transition_allowed(self, new_state):
        """Data integrity, not permission: it holds for sudo and admins too."""
        for record in self:
            if record.state == new_state:
                continue
            if new_state not in self._STATE_TRANSITIONS.get(record.state, set()):
                raise ValidationError(_(
                    "Invalid admission status change from '%(old)s' to '%(new)s'."
                ) % {'old': record.state, 'new': new_state})

    _ACCEPTED_LOCKED_FIELDS = {
        'admission_path', 'faculty_id', 'program_id', 'academic_year_id',
        'email', 'registration_fee', 'registration_fee_paid', 'document_line_ids',
    }
    _REGISTERED_LOCKED_FIELDS = _ACCEPTED_LOCKED_FIELDS | {
        'name', 'phone', 'previous_school', 'registration_date',
        'reregistration_fee', 'reregistration_fee_paid',
    }

    def _check_post_acceptance_locks(self, vals):
        """Freeze academic choice, checklist, and settled fees once decided."""
        if self._REGISTERED_LOCKED_FIELDS.intersection(vals):
            finalized = self.filtered(lambda r: r.state in ('registered', 'rejected'))
            if finalized:
                raise ValidationError(_(
                    "Core admission details, fees, and documents cannot be modified once an application is %(state)s."
                ) % {'state': finalized[0].state})
        if self._ACCEPTED_LOCKED_FIELDS.intersection(vals):
            accepted = self.filtered(lambda r: r.state == 'accepted')
            if accepted:
                raise ValidationError(_(
                    "Application details, documents, and registration fees are locked after acceptance."
                ))

    def _write_state(self, new_state):
        """Perform a state change authorized by a workflow action method."""
        self.with_context(_pmb_state_token=_STATE_TRANSITION_TOKEN).write({'state': new_state})

    def write(self, vals):
        is_token = self.env.context.get('_pmb_state_token') is _STATE_TRANSITION_TOKEN
        is_admin = self.env.su or self.env.user.has_group('campus_core.group_campus_administrator')
        if not is_token and not is_admin and self._SYSTEM_MANAGED_FIELDS.intersection(vals):
            raise AccessError(_(
                "Registration number, student profile, and portal user links cannot be modified directly."
            ))
        if not is_token and not is_admin and ('registration_fee' in vals or 'reregistration_fee' in vals):
            Program = self.env['academic.program'].sudo()
            for record in self:
                path = vals.get('admission_path', record.admission_path)
                program = (
                    Program.browse(vals['program_id'])
                    if 'program_id' in vals and vals['program_id']
                    else (Program.browse() if 'program_id' in vals else record.program_id)
                )
                exp_reg, exp_rereg = self._expected_configured_fees(path, program)
                if (
                    'registration_fee' in vals
                    and float_compare(vals['registration_fee'] or 0.0, exp_reg, precision_digits=2) != 0
                ):
                    raise AccessError(_(
                        "Only Campus Administrators can manually override configured admission fees."
                    ))
                if (
                    'reregistration_fee' in vals
                    and float_compare(vals['reregistration_fee'] or 0.0, exp_rereg, precision_digits=2) != 0
                ):
                    raise AccessError(_(
                        "Only Campus Administrators can manually override configured admission fees."
                    ))
        self._check_post_acceptance_locks(vals)
        if 'email' in vals and vals['email']:
            vals = dict(vals, email=str(vals['email']).strip().lower())
        if 'state' in vals:
            self._check_state_transition_allowed(vals['state'])
            changing = self.filtered(lambda r: r.state != vals['state'])
            if changing and not is_token:
                raise ValidationError(_(
                    "Admission status cannot be changed directly; use the workflow action buttons."
                ))
        path_changing = (
            self.filtered(lambda r: r.state in ('draft', 'submitted', 'document_review') and r.admission_path != vals['admission_path'])
            if 'admission_path' in vals else self.browse()
        )
        res = super().write(vals)
        if not self.env.su and ('program_id' in vals or 'faculty_id' in vals):
            self.flush_recordset()
            self.check_access('write')
        if path_changing:
            path_changing._ensure_default_documents(prune_unreceived=True)
        return res

    def unlink(self):
        protected = self.filtered(lambda r: r.state in ('accepted', 'registered', 'rejected'))
        if protected:
            raise ValidationError(_(
                "Accepted, registered, or rejected admissions cannot be deleted."
            ))
        return super().unlink()

    def _pmb_activity_assignee(self, program, jurisdictions=None, pmb_group=None):
        """Return an active PMB officer covering ``program`` or fallback to current user."""
        if jurisdictions is None:
            jurisdictions = self.env['campus.jurisdiction'].sudo().search([
                ('scope', '=', 'pmb'),
                ('employee_id.active', '=', True),
            ])
        for row in jurisdictions:
            user = row.employee_id.user_id
            if not user or not user.active or user._is_public():
                continue
            if not user.has_group('campus_pmb.group_pmb'):
                continue
            if row._covers_program(program):
                return user
        return self.env.user if not self.env.user._is_public() else self.env['res.users']

    def _schedule_pmb_activity(self, xmlid, summary_by_record):
        activity_type = self.env.ref(xmlid, raise_if_not_found=False)
        if not activity_type or not self:
            return
        pmb_group = self.env.ref('campus_pmb.group_pmb', raise_if_not_found=False)
        jurisdictions = self.env['campus.jurisdiction'].sudo().search([
            ('scope', '=', 'pmb'),
            ('employee_id.active', '=', True),
        ])
        assignee_by_program = {}
        for record in self:
            prog_id = record.program_id.id
            if prog_id not in assignee_by_program:
                assignee_by_program[prog_id] = record._pmb_activity_assignee(
                    record.program_id, jurisdictions=jurisdictions, pmb_group=pmb_group,
                )
            assignee = assignee_by_program[prog_id]
            if not assignee:
                continue
            open_same = record.activity_ids.filtered(
                lambda act: act.activity_type_id == activity_type
            )
            if not open_same:
                summary = summary_by_record(record) if callable(summary_by_record) else summary_by_record
                record.activity_schedule(xmlid, user_id=assignee.id, summary=summary)

    def _schedule_review_and_payment_activities(self, review_summary_tpl):
        self._schedule_pmb_activity(
            'campus_pmb.mail_activity_type_document_review',
            lambda rec: review_summary_tpl % (rec.name or '-'),
        )
        unpaid = self.filtered(lambda rec: rec.registration_fee > 0 and not rec.registration_fee_paid)
        if unpaid:
            pay_tpl = _("Verify registration fee payment for %s")
            unpaid._schedule_pmb_activity(
                'campus_pmb.mail_activity_type_payment_verification',
                lambda rec: pay_tpl % (rec.name or '-'),
            )

    def _check_registration_fee_paid(self, error_message):
        unpaid_reg = self.filtered(
            lambda record: record.registration_fee > 0 and not record.registration_fee_paid
        )
        if unpaid_reg:
            raise UserError(error_message)

    def _require_state(self, allowed_states):
        """Refuse the action unless every record is in one of these states.

        Every transition goes through here. Two of them used to hand-roll the
        same check with their own wording, so a user met two different messages
        for the same kind of refusal and the shared helper could be changed
        without those two following.
        """
        wrong = self.filtered(lambda record: record.state not in allowed_states)
        if wrong:
            raise UserError(_(
                "This action is not allowed from the current admission status."
            ))

    def action_submit(self):
        self._require_state({'draft'})
        self._ensure_default_documents()
        self._write_state('submitted')
        self._schedule_review_and_payment_activities(
            _("Review admission documents for %s"),
        )

    def action_start_document_review(self):
        self._require_state({'submitted'})
        self._write_state('document_review')
        self._schedule_review_and_payment_activities(
            _("Complete document verification for %s"),
        )

    def _check_pmb_staff(self, action_label):
        """Ensure only PMB staff or Campus Administrators run admission decisions."""
        if self.env.su:
            return
        user = self.env.user
        if user.has_group('campus_pmb.group_pmb') or user.has_group('campus_core.group_campus_administrator'):
            self.check_access('write')
            return
        raise AccessError(_("Only PMB staff or Campus Administrators can %s.") % action_label)

    def _check_may_accept(self):
        """Accepting an applicant is a PMB decision, not an ordinary edit."""
        self._check_pmb_staff(_("accept an application"))

    def action_reject(self):
        self._require_state({'draft', 'submitted', 'document_review', 'accepted'})
        self._check_pmb_staff(_("reject an application"))
        already_linked = self.filtered(lambda r: r.partner_id or r.user_id)
        if already_linked:
            raise UserError(_("Admissions that already have a linked student account cannot be rejected."))
        self.activity_feedback([
            'campus_pmb.mail_activity_type_document_review',
            'campus_pmb.mail_activity_type_payment_verification',
            'campus_pmb.mail_activity_type_create_account',
        ])
        self._write_state('rejected')

    def action_accept(self):
        """The single path into the 'accepted' state.

        _check_may_accept stays on THIS path deliberately: accepting an
        applicant is a PMB decision, and the group check is the only thing that
        makes it one.
        """
        self._require_state({'document_review'})
        self._check_may_accept()
        incomplete = self.filtered(lambda record: not record.documents_complete)
        if incomplete:
            raise UserError(_("All required documents must be received first."))
        self._check_registration_fee_paid(
            _("Registration fee must be paid before accepting an applicant.")
        )
        self._write_state('accepted')
        self.activity_feedback([
            'campus_pmb.mail_activity_type_document_review',
            'campus_pmb.mail_activity_type_payment_verification',
        ])
        account_tpl = _("Create student portal account and NIM for %s")
        self._schedule_pmb_activity(
            'campus_pmb.mail_activity_type_create_account',
            lambda rec: account_tpl % (rec.name or '-'),
        )
        unpaid_rereg = self.filtered(
            lambda rec: rec.reregistration_fee > 0 and not rec.reregistration_fee_paid
        )
        if unpaid_rereg:
            rereg_tpl = _("Verify re-registration fee payment for %s")
            unpaid_rereg._schedule_pmb_activity(
                'campus_pmb.mail_activity_type_payment_verification',
                lambda rec: rereg_tpl % (rec.name or '-'),
            )

    def action_register(self):
        self._check_pmb_staff(_("register a student"))
        if self.ids:
            self.flush_recordset()
            self.env.cr.execute(SQL(
                "SELECT id FROM %s WHERE id IN %s ORDER BY id FOR UPDATE NOWAIT",
                SQL.identifier(self._table), tuple(sorted(self.ids)),
            ))
            self.invalidate_recordset(['state', 'user_id', 'partner_id'])
        self._require_state({'accepted'})
        self._check_registration_fee_paid(
            _("Registration fee must be paid before registering a student.")
        )
        unpaid_rereg = self.filtered(
            lambda record: record.reregistration_fee > 0 and not record.reregistration_fee_paid
        )
        if unpaid_rereg:
            raise UserError(_("Re-registration fee must be paid before registering a student."))
        # Pre-validate every record before generating any NIM sequences so a
        # batch failure on record #N never burns NIM numbers for #1..#N-1.
        self._prevalidate_account_creation()
        for record in self:
            record._create_account()
        self._write_state('registered')
        self.activity_feedback([
            'campus_pmb.mail_activity_type_create_account',
            'campus_pmb.mail_activity_type_payment_verification',
        ])

    def _intake_year(self, academic_year):
        """Four-digit intake year taken from an academic year named like '2025/2026'."""
        match = re.search(r'\d{4}', (academic_year.name or '') if academic_year else '')
        if match:
            return match.group(0)
        return fields.Date.context_today(self).strftime('%Y')

    def _generate_nim(self, faculty_id, program_id, academic_year=None):
        """Generate a unique NIM (Student ID Number) based on faculty, program, and year.
        Format: {FACULTY_ABBR}-{PROG_ABBR}-{YY}-{SEQUENCE:04d}
        e.g., TI-IF-26-0001

        The intake year comes from the admission's academic year, not from
        today's date. Registering a 2026 intake in December 2025 used to stamp
        the student with a 2025 NIM and batch year, which then disagreed with
        every other record of that cohort.
        """
        batch_year = self._intake_year(academic_year)
        year_short = batch_year[-2:]

        # From the stored codes, not from the current display names. This used
        # to take the initials of faculty_id.name and program_id.name, so
        # renaming "Fakultas Teknik" to "Fakultas Teknologi Industri" changed
        # the prefix for every student admitted afterwards - one faculty's
        # cohort split across two numbering series, with nothing in the data to
        # say they were the same place. academic.faculty.code and
        # academic.program.code are seeded from those initials on creation and
        # locked once a NIM has been issued from them.
        faculty_str = (faculty_id.code or '').strip().upper() or 'FA'
        program_str = (program_id.code or '').strip().upper() or 'PR'

        prefix = f"{faculty_str}-{program_str}-{year_short}-"
        seq_code = f"student.nim.{prefix}"

        # Serialize sequence creation per prefix using a namespaced 2-arg advisory lock.
        lock_key = zlib.crc32(seq_code.encode('utf-8')) & 0x7FFFFFFF
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_NIM_LOCK_CLASSID, lock_key))
        seq = self.env['ir.sequence'].sudo().search([('code', '=', seq_code)], limit=1)
        if not seq:
            seq = self.env['ir.sequence'].sudo().create({
                'name': f'NIM Sequence {prefix}',
                'code': seq_code,
                'implementation': 'standard',
                'prefix': prefix,
                'padding': 4,
                'company_id': False,
            })

        nim_str = seq.next_by_id()
        return nim_str, batch_year

    def _find_account_targets(self):
        """Resolve existing user/partner collisions for a single admission record."""
        self.ensure_one()
        if self.state not in ('accepted', 'registered'):
            raise UserError(_("Only accepted applicants can have a portal account created."))
        if not self.email:
            raise UserError(_("Email is required to create a Portal account."))
        if self.user_id:
            raise UserError(_("A portal account has already been created."))

        email_clean = self.email.strip().lower()
        email_pattern = _escape_like(email_clean)
        Users = self.env['res.users'].sudo().with_context(active_test=False)
        existing_user = Users.search([('login', '=ilike', email_pattern)], limit=1)
        if existing_user:
            if not existing_user.active:
                raise UserError(_(
                    "The email %(email)s belongs to an archived account (%(name)s). "
                    "Please contact an administrator to reactivate or resolve it first."
                ) % {'email': self.email, 'name': existing_user.partner_id.display_name})
            if existing_user._is_internal() or not existing_user.partner_id.is_student:
                raise UserError(_(
                    "The email %(email)s already belongs to another account in "
                    "the system (%(name)s), which is not a student portal account. Register "
                    "this applicant with a different email address, or ask an "
                    "administrator to resolve the two accounts first."
                ) % {
                    'email': self.email,
                    'name': existing_user.partner_id.display_name,
                })
            return email_clean, existing_user, existing_user.partner_id

        partner = self.env['res.partner'].sudo().with_context(active_test=False).search([
            ('email', '=ilike', email_pattern),
            ('is_student', '=', True),
        ], limit=1)
        if partner:
            existing_partner_users = partner.with_context(active_test=False).user_ids
            if existing_partner_users:
                raise UserError(_(
                    "A student profile with email %(email)s already has a linked user account "
                    "under a different login. Please ask an administrator to reconcile the accounts."
                ) % {'email': self.email})
        return email_clean, self.env['res.users'], partner

    def _prevalidate_account_creation(self):
        seen_emails = set()
        for record in self:
            email_clean, _user, _partner = record._find_account_targets()
            if email_clean in seen_emails:
                raise UserError(_(
                    "Duplicate email '%s' found in the same registration batch."
                ) % email_clean)
            seen_emails.add(email_clean)

    def _create_account(self):
        for record in self:
            email_clean, existing_user, partner = record._find_account_targets()
            if existing_user:
                record.with_context(_pmb_state_token=_STATE_TRANSITION_TOKEN).write({
                    'user_id': existing_user.id,
                    'partner_id': existing_user.partner_id.id,
                })
                update_vals = {'is_student': True, 'program_id': record.program_id.id}
                if not existing_user.partner_id.nim:
                    nim, batch_year = record._generate_nim(
                        record.faculty_id, record.program_id, record.academic_year_id,
                    )
                    update_vals.update({'nim': nim, 'batch_year': batch_year})
                existing_user.partner_id.sudo().write(update_vals)
                continue

            nim = batch_year = None
            if not partner or not partner.nim:
                nim, batch_year = record._generate_nim(
                    record.faculty_id, record.program_id, record.academic_year_id,
                )

            if partner:
                partner_vals = {
                    'name': record.name,
                    'is_student': True,
                    'active': True,
                    'program_id': record.program_id.id,
                }
                if record.phone:
                    partner_vals['phone'] = record.phone
                if not partner.nim:
                    partner_vals.update({'nim': nim, 'batch_year': batch_year})
                partner.sudo().write(partner_vals)
            else:
                partner = self.env['res.partner'].sudo().create({
                    'name': record.name,
                    'email': email_clean,
                    'phone': record.phone,
                    'is_student': True,
                    'nim': nim,
                    'batch_year': batch_year,
                    'program_id': record.program_id.id,
                    'company_id': self.env.company.id,
                })

            portal_group = self.env.ref('base.group_portal')
            # Generate a cryptographically secure random initial password and
            # prepare an Odoo signup/password-setup token instead of deriving
            # predictable credentials from the applicant's email prefix.
            initial_password = secrets.token_urlsafe(24)
            user = self.env['res.users'].sudo().create({
                'name': record.name,
                'login': email_clean,
                'password': initial_password,
                'partner_id': partner.id,
                'group_ids': [Command.set([portal_group.id])],
                'company_id': self.env.company.id,
            })
            partner.sudo().signup_prepare()
            record.with_context(_pmb_state_token=_STATE_TRANSITION_TOKEN).write({
                'partner_id': partner.id,
                'user_id': user.id,
            })
            _logger.info(
                "Created Portal User and Partner for student NIM: %s (Email: %s)",
                partner.nim or nim,
                record.email,
            )

    # The only fields an anonymous website visitor may supply. Everything else on
    # campus.admission is decided by the server. This list is the security
    # boundary for the public /admission/submit route: the request dict must
    # never be passed to create() wholesale, or a visitor could set `state`,
    # `registration_number`, `partner_id` or `user_id` themselves.
    _PORTAL_WRITABLE_FIELDS = ('name', 'email', 'phone', 'previous_school', 'admission_path')
    _PORTAL_MAX_LENGTHS = {
        'name': 255,
        'email': 254,
        'phone': 32,
        'previous_school': 255,
    }

    @staticmethod
    def _parse_optional_int_id(value):
        if value in (None, False, ''):
            return False
        if isinstance(value, bool):
            raise ValidationError(_("Invalid faculty or program selection."))
        parsed = int(value)
        if parsed <= 0 or parsed > _PG_INT4_MAX:
            raise ValidationError(_("Invalid faculty or program selection."))
        return parsed

    @staticmethod
    def _clean_portal_text(value, field_label):
        if value is None or value is False:
            return ''
        if not isinstance(value, str):
            raise ValidationError(_("Field '%s' must be a text value.") % field_label)
        if '\x00' in value:
            raise ValidationError(_("Field '%s' contains invalid characters.") % field_label)
        return value.strip()

    @api.model
    def _create_admission_from_portal(self, post_data):
        """Create an admission from the public website form."""
        try:
            faculty_id = self._parse_optional_int_id(post_data.get('faculty_id'))
            program_id = self._parse_optional_int_id(post_data.get('program_id'))
        except (ValueError, TypeError):
            raise ValidationError(_("Invalid faculty or program selection."))

        if not program_id or program_id <= 0:
            raise ValidationError(_("Invalid study programme selection."))

        program = self.env['academic.program'].sudo().search(
            [('id', '=', program_id)], limit=1,
        )
        if not program:
            raise ValidationError(_("Invalid study programme selection."))
        if faculty_id and program.faculty_id.id != faculty_id:
            raise ValidationError(_("Program does not belong to the selected faculty."))
        if not faculty_id:
            faculty_id = program.faculty_id.id
        if faculty_id and not self.env['academic.faculty'].sudo().search_count(
            [('id', '=', faculty_id)],
        ):
            raise ValidationError(_("Invalid faculty selection."))

        active_year = self.env['academic.year'].sudo()._get_current()
        if not active_year:
            raise ValidationError(_("No active academic year found for admission."))

        vals = {}
        for field in self._PORTAL_WRITABLE_FIELDS:
            raw_val = post_data.get(field)
            if raw_val in (None, False, ''):
                continue
            cleaned_val = self._clean_portal_text(raw_val, field)
            if cleaned_val:
                vals[field] = cleaned_val

        if not vals.get('name') or not vals.get('email'):
            raise ValidationError(_("Applicant name and email address are required."))
        vals['email'] = vals['email'].lower()
        for field, max_len in self._PORTAL_MAX_LENGTHS.items():
            if vals.get(field) and len(vals[field]) > max_len:
                raise ValidationError(_(
                    "Field '%(field)s' exceeds the maximum allowed length of %(max)s characters."
                ) % {'field': field, 'max': max_len})

        admission_path = vals.get('admission_path') or 'regular'
        if admission_path not in dict(self._admission_path_selection()):
            raise ValidationError(_("Invalid admission path selection."))
        vals['admission_path'] = admission_path

        duplicate_msg = _(
            "An application with this email address already exists for this "
            "academic year. Please contact the admissions office if you need "
            "to change it."
        )
        if vals.get('email') and self.sudo().search_count([
            ('email', '=ilike', _escape_like(vals['email'])),
            ('academic_year_id', '=', active_year.id),
        ]):
            raise ValidationError(duplicate_msg)

        vals.update({
            'faculty_id': faculty_id,
            'program_id': program_id,
            'academic_year_id': active_year.id,
            'state': 'draft',
        })
        try:
            with self.env.cr.savepoint():
                record = self.sudo().create(vals)
                record.flush_recordset()
                return record
        except IntegrityError as err:
            if getattr(err, 'pgcode', None) == '23505':
                raise ValidationError(duplicate_msg)
            raise


class CampusAdmissionRequirement(models.Model):
    """Which documents a given admission path asks for.

    The default checklist used to be a hard-coded list of four selection keys
    inside _default_document_types, so a campus that wanted a fifth document -
    or different documents for a transfer applicant than for a regular one -
    had to change Python and redeploy. It is registrar configuration, like the
    grade scale and the credit limits beside it.

    Shipped as noupdate data, so the four it starts with are a starting point an
    administrator may edit, not something an upgrade puts back.
    """

    _name = 'campus.admission.requirement'
    _description = 'Admission Document Requirement'
    _order = 'sequence, id'

    name = fields.Char(string='Label', compute='_compute_name')
    sequence = fields.Integer(default=10)
    document_type = fields.Selection(
        selection=lambda self: self.env['campus.admission.document']._document_type_selection(),
        string='Document Type', required=True,
    )
    admission_path = fields.Selection(
        selection=lambda self: [('all', _('All Paths'))] + self.env['campus.admission']._admission_path_selection(),
        string='Admission Path', default='all', required=True,
        help="Which applicants are asked for this document. 'All Paths' covers every one.",
    )
    required = fields.Boolean(string='Required', default=True)

    _unique_requirement = models.Constraint(
        'UNIQUE (document_type, admission_path)',
        "A document type may only be listed once per admission path.",
    )

    @api.depends('document_type', 'admission_path')
    def _compute_name(self):
        types = dict(self.env['campus.admission.document']._document_type_selection())
        paths = dict([('all', _('All Paths'))] + self.env['campus.admission']._admission_path_selection())
        for record in self:
            record.name = '%s - %s' % (
                types.get(record.document_type, ''), paths.get(record.admission_path, ''),
            )


class CampusAdmissionDocument(models.Model):
    _name = 'campus.admission.document'
    _description = 'Admission Document Checklist'
    _order = 'admission_id, document_type'

    @api.model
    def _document_type_selection(self):
        """One definition of the document types, shared with the requirements."""
        return [
            ('identity_card', _('Identity Card')),
            ('family_card', _('Family Card')),
            ('diploma', _('Diploma or Graduation Letter')),
            ('photo', _('Photo')),
            ('transcript', _('Transcript')),
            ('other', _('Other')),
        ]

    @api.model
    def _default_document_specs(self, admission_path=None):
        """Return ``[(document_type, required), ...]`` for the given admission path.

        Reads ``campus.admission.requirement`` and preserves each requirement's
        ``required`` flag. A path-specific rule overrides an ``all`` rule while
        keeping the first-seen sequence order.
        """
        domain = [
            ('admission_path', 'in', ['all', admission_path] if admission_path else ['all']),
        ]
        requirements = self.env['campus.admission.requirement'].sudo().search(domain)
        if not requirements:
            return [(doc_type, True) for doc_type in ('identity_card', 'family_card', 'diploma', 'photo')]
        specs = {}
        ranks = {}
        for req in requirements:
            is_path_specific = req.admission_path != 'all'
            if req.document_type not in specs or is_path_specific >= ranks[req.document_type]:
                specs[req.document_type] = req.required
                ranks[req.document_type] = is_path_specific
        return list(specs.items())

    @api.model
    def _default_document_types(self, admission_path=None):
        """The checklist an applicant on this path is asked for.

        Read from campus.admission.requirement, which an administrator can edit,
        rather than from a list written into this method. Falls back to the four
        the module ships only when nothing at all is configured, so a
        half-set-up campus still produces a usable checklist.
        """
        return [doc_type for doc_type, _required in self._default_document_specs(admission_path)]

    admission_id = fields.Many2one(
        'campus.admission', string='Admission', required=True, ondelete='cascade'
    )
    document_type = fields.Selection(
        selection=lambda self: self._document_type_selection(),
        string='Document Type', required=True,
    )
    required = fields.Boolean(string='Required', default=True)
    received = fields.Boolean(string='Received')
    note = fields.Char(string='Note')

    _unique_document_type_per_admission = models.Constraint(
        'UNIQUE (admission_id, document_type)',
        "Each document type can only appear once per admission.",
    )

    def _check_admission_mutable(self):
        frozen = self.filtered(
            lambda line: line.admission_id.state in ('accepted', 'registered', 'rejected')
        )
        if frozen:
            raise ValidationError(_(
                "Document checklists cannot be modified once an admission is accepted, registered, or rejected."
            ))

    @api.model_create_multi
    def create(self, vals_list):
        adm_ids = {vals['admission_id'] for vals in vals_list if vals.get('admission_id')}
        if adm_ids:
            frozen = self.env['campus.admission'].browse(list(adm_ids)).filtered(
                lambda adm: adm.state in ('accepted', 'registered', 'rejected')
            )
            if frozen:
                raise ValidationError(_(
                    "Documents cannot be added once an admission is accepted, registered, or rejected."
                ))
        return super().create(vals_list)

    def write(self, vals):
        self._check_admission_mutable()
        is_token = self.env.context.get('_pmb_state_token') is _STATE_TRANSITION_TOKEN
        is_admin = self.env.su or self.env.user.has_group('campus_core.group_campus_administrator')
        if 'required' in vals and not is_admin and not is_token:
            raise AccessError(_("Only Campus Administrators can change whether an admission document is required."))
        if 'admission_id' in vals:
            target = (
                self.env['campus.admission'].browse(vals['admission_id'])
                if vals['admission_id'] else self.env['campus.admission']
            )
            if not target or target.state in ('accepted', 'registered', 'rejected'):
                raise ValidationError(_(
                    "Document checklists cannot be modified once an admission is accepted, registered, or rejected."
                ))
        res = super().write(vals)
        if not self.env.su and 'admission_id' in vals:
            self.flush_recordset()
            self.check_access('write')
        return res

    def unlink(self):
        self._check_admission_mutable()
        is_token = self.env.context.get('_pmb_state_token') is _STATE_TRANSITION_TOKEN
        is_admin = self.env.su or self.env.user.has_group('campus_core.group_campus_administrator')
        if not is_admin and not is_token and self.filtered('required'):
            raise AccessError(_("Only Campus Administrators can delete required admission document lines."))
        return super().unlink()


class CampusAdmissionFee(models.Model):
    """Fee configuration for registration and re-registration (daftar ulang).

    Both fees live in one table under Admissions > Configuration > Admission Fees:
    - Registration Fee ('registration'): usually varies by Admission Path
      (e.g. Regular, Transfer, Scholarship). Checked before an applicant can be
      accepted.
    - Re-registration Fee ('reregistration'): usually varies by Study Program
      (program_id) and/or Admission Path. Checked before an accepted applicant
      can be registered as an active student.
    """

    _name = 'campus.admission.fee'
    _description = 'Admission Fee'
    _order = 'sequence, fee_type, id'

    @api.model
    def _fee_type_selection(self):
        return [
            ('registration', _('Registration Fee')),
            ('reregistration', _('Re-registration Fee')),
        ]

    name = fields.Char(string='Label', compute='_compute_name')
    sequence = fields.Integer(default=10)
    fee_type = fields.Selection(
        selection=lambda self: self._fee_type_selection(),
        string='Fee Type', required=True, default='registration',
    )
    admission_path = fields.Selection(
        selection=lambda self: [('all', _('All Paths'))] + self.env['campus.admission']._admission_path_selection(),
        string='Admission Path', default='all', required=True,
        help="Which applicants this fee applies to. 'All Paths' covers every path unless overridden.",
    )
    program_id = fields.Many2one(
        'academic.program', string='Program',
        help="Leave empty to apply to all study programs.",
    )
    amount = fields.Monetary(
        string='Amount', required=True, default=0.0, currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        compute='_compute_currency_id',
        default=lambda self: self.env.company.currency_id,
    )

    _compute_currency_id = CampusAdmission._compute_currency_id

    _unique_fee_rule = models.UniqueIndex(
        "(fee_type, admission_path, COALESCE(program_id, 0))",
        "A fee rule for this fee type, admission path, and study program already exists.",
    )

    @api.constrains('amount')
    def _check_amount(self):
        for record in self:
            if record.amount < 0:
                raise ValidationError(_("Fee amount cannot be negative."))

    @api.depends('fee_type', 'admission_path', 'program_id')
    def _compute_name(self):
        fee_types = dict(self._fee_type_selection())
        paths = dict([('all', _('All Paths'))] + self.env['campus.admission']._admission_path_selection())
        for record in self:
            parts = [
                fee_types.get(record.fee_type, ''),
                paths.get(record.admission_path, ''),
            ]
            if record.program_id:
                parts.append(record.program_id.name)
            record.name = ' - '.join(filter(None, parts))

    @api.model
    def _build_fee_index(self, rules=None):
        """Pre-index fee rules into a dict for O(1) lookups across paths/programs."""
        all_rules = self.sudo().search([]) if rules is None else rules
        return {
            (r.fee_type, r.admission_path, r.program_id.id or False): r.amount
            for r in all_rules
        }

    @staticmethod
    def _lookup_fee_from_index(fee_index, fee_type, admission_path=None, program=None):
        """Resolve a fee amount in O(1) following the 4-tier specificity precedence."""
        prog_id = program.id if program else False
        candidates = []
        if admission_path:
            if prog_id:
                candidates.append((fee_type, admission_path, prog_id))
            candidates.append((fee_type, admission_path, False))
        if prog_id:
            candidates.append((fee_type, 'all', prog_id))
        candidates.append((fee_type, 'all', False))
        for key in candidates:
            if key in fee_index:
                return fee_index[key]
        return 0.0

    @api.model
    def _get_fee_amount(
        self, fee_type, admission_path=None, program=None, rules=None,
    ):
        """Return the configured fee amount for the given type, path, and program."""
        if rules is not None:
            fee_index = self._build_fee_index(rules=rules)
            return self._lookup_fee_from_index(fee_index, fee_type, admission_path, program)
        allowed_paths = {'all', admission_path} if admission_path else {'all'}
        allowed_programs = {program.id, False} if program else {False}
        matching_rules = self.sudo().search([
            ('fee_type', '=', fee_type),
            ('admission_path', 'in', list(allowed_paths)),
            ('program_id', 'in', list(allowed_programs)),
        ])
        fee_index = self._build_fee_index(rules=matching_rules)
        return self._lookup_fee_from_index(fee_index, fee_type, admission_path, program)
