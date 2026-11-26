import logging
import re
import zlib
from odoo import _, api, fields, models, Command
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)
# Unforgeable per-process sentinel: prevents JSON-RPC callers from passing a
# truthy context flag to bypass action_accept() / action_register() via write().
_STATE_TRANSITION_TOKEN = object()


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
        # Must NOT be translated. create() below compares this against the
        # literal 'New' to decide whether to draw a sequence number. With _()
        # an Indonesian session produced "Baru" (campus_pmb/i18n/id.po), the
        # comparison failed, the sequence was never called, and every
        # application was saved with the registration number "Baru".
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
        'academic.faculty', string='Faculty', required=True, tracking=True,
    )
    program_id = fields.Many2one(
        'academic.program', string='Program', required=True, tracking=True,
        domain="[('faculty_id', '=', faculty_id)]",
    )
    academic_year_id = fields.Many2one(
        'academic.year', string='Academic Year', required=True, tracking=True,
    )

    partner_id = fields.Many2one(
        'res.partner', string='Student Profile', readonly=True, tracking=True, copy=False
    )
    user_id = fields.Many2one(
        'res.users', string='Portal User', readonly=True, tracking=True, copy=False
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

    # Case-sensitive on purpose for now: Budi@x.com and budi@x.com are two
    # applications. Lower-casing on write is the obvious fix, but it has to be
    # paired with a migration that folds the rows already stored, and folding
    # them can collide with this very constraint - two applicants who really are
    # two people, typed differently. Doing it properly means deciding what
    # happens to each collision, which is a registrar's call. Stated here rather
    # than deferred to an "audit checklist" that is not in this repository.
    _email_year_unique = models.Constraint(
        'UNIQUE (email, academic_year_id)',
        "An admission record already exists for this email in this academic year.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('registration_number', 'New') == 'New':
                vals['registration_number'] = (
                    self.env['ir.sequence'].sudo().next_by_code('campus.admission') or 'New'
                )
        for vals in vals_list:
            # Same reason as the write guard: creating straight into a later
            # state would skip every step that produces the student's account.
            if vals.get('state') and vals['state'] != 'draft':
                raise ValidationError(_("New admissions must start in draft status."))
        # The checklist goes into the same insert. It used to be a second write
        # per record right after create, which also re-triggered tracking and
        # the document progress compute for every new applicant.
        Document = self.env['campus.admission.document']
        for vals in vals_list:
            if not vals.get('document_line_ids'):
                vals['document_line_ids'] = [
                    Command.create({'document_type': document_type, 'required': required})
                    for document_type, required in Document._default_document_specs(
                        vals.get('admission_path', 'regular'),
                    )
                ]
        records = super().create(vals_list)
        # Still called for the rows that arrived carrying their own checklist:
        # a partial list must still be topped up with the missing types.
        records._ensure_default_documents()
        return records

    @api.depends('document_line_ids.required', 'document_line_ids.received')
    def _compute_document_progress(self):
        for record in self:
            required_lines = record.document_line_ids.filtered('required')
            received_lines = required_lines.filtered('received')
            record.required_document_count = len(required_lines)
            record.received_document_count = len(received_lines)
            record.documents_complete = bool(required_lines) and len(required_lines) == len(received_lines)

    @api.depends('admission_path', 'program_id')
    def _compute_fees(self):
        Fee = self.env['campus.admission.fee']
        all_rules = Fee.sudo().search([])
        for record in self:
            if record.state in ('accepted', 'registered'):
                # Preserve historical fees once acceptance is finalized.
                continue
            record.registration_fee = Fee._get_fee_amount(
                'registration',
                admission_path=record.admission_path,
                program=record.program_id,
                rules=all_rules,
            )
            record.reregistration_fee = Fee._get_fee_amount(
                'reregistration',
                admission_path=record.admission_path,
                program=record.program_id,
                rules=all_rules,
            )

    def _ensure_default_documents(self, prune_unreceived=False):
        Document = self.env['campus.admission.document']
        for record in self:
            default_specs = Document._default_document_specs(record.admission_path)
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
                record.write({'document_line_ids': commands})

    # The admission state graph, mirrored on academic.krs. The buttons already
    # enforced their own order, but nothing enforced it on a plain write, so a
    # PMB officer or administrator could set state='registered' straight from
    # the list view, an import or a server action. action_register and therefore
    # _create_account never ran, leaving a record that reads Registered with no
    # NIM, no student contact and no portal account — a student who exists on
    # the admission list and nowhere else in the system.
    _STATE_TRANSITIONS = {
        'draft': {'submitted', 'rejected'},
        'submitted': {'document_review', 'rejected'},
        'document_review': {'accepted', 'rejected'},
        'accepted': {'registered'},
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
        'reregistration_fee', 'reregistration_fee_paid',
    }

    def _check_post_acceptance_locks(self, vals):
        """Freeze academic choice, checklist, and settled fees once decided."""
        if self.env.context.get('pmb_skip_lock'):
            return
        if _REGISTERED_LOCKED_FIELDS := self._REGISTERED_LOCKED_FIELDS.intersection(vals):
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
        self._check_post_acceptance_locks(vals)
        if 'state' in vals:
            self._check_state_transition_allowed(vals['state'])
            changing = self.filtered(lambda r: r.state != vals['state'])
            if changing and self.env.context.get('_pmb_state_token') is not _STATE_TRANSITION_TOKEN:
                raise ValidationError(_(
                    "Admission status cannot be changed directly; use the workflow action buttons."
                ))
        path_changing = (
            self.filtered(lambda r: r.state in ('draft', 'submitted', 'document_review') and r.admission_path != vals['admission_path'])
            if 'admission_path' in vals else self.browse()
        )
        res = super().write(vals)
        if path_changing:
            path_changing._ensure_default_documents(prune_unreceived=True)
        return res

    def _pmb_activity_assignee(self, program):
        """Return an active PMB officer covering ``program`` or fallback to current user."""
        pmb_group = self.env.ref('campus_pmb.group_pmb', raise_if_not_found=False)
        jurisdictions = self.env['campus.jurisdiction'].sudo().search([
            ('scope', '=', 'pmb'),
            ('employee_id.active', '=', True),
        ])
        for row in jurisdictions:
            user = row.employee_id.user_id
            if not user or not user.active or user._is_public():
                continue
            if pmb_group and pmb_group not in user.group_ids:
                continue
            if row._covers_program(program):
                return user
        return self.env.user if not self.env.user._is_public() else self.env['res.users']

    def _schedule_pmb_activity(self, xmlid, summary):
        activity_type = self.env.ref(xmlid, raise_if_not_found=False)
        if not activity_type:
            return
        for record in self:
            assignee = record._pmb_activity_assignee(record.program_id)
            if not assignee:
                continue
            open_same = record.activity_ids.filtered(
                lambda act: act.activity_type_id == activity_type
            )
            if not open_same:
                record.activity_schedule(xmlid, user_id=assignee.id, summary=summary)

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
        for record in self:
            name = record.name or '-'
            record._schedule_pmb_activity(
                'campus_pmb.mail_activity_type_document_review',
                _("Review admission documents for %s") % name,
            )
            if record.registration_fee > 0 and not record.registration_fee_paid:
                record._schedule_pmb_activity(
                    'campus_pmb.mail_activity_type_payment_verification',
                    _("Verify registration fee payment for %s") % name,
                )

    def action_start_document_review(self):
        self._require_state({'submitted'})
        self._write_state('document_review')
        for record in self:
            name = record.name or '-'
            record._schedule_pmb_activity(
                'campus_pmb.mail_activity_type_document_review',
                _("Complete document verification for %s") % name,
            )
            if record.registration_fee > 0 and not record.registration_fee_paid:
                record._schedule_pmb_activity(
                    'campus_pmb.mail_activity_type_payment_verification',
                    _("Verify registration fee payment for %s") % name,
                )

    def _check_may_accept(self):
        """Accepting an applicant is a PMB decision, not an ordinary edit."""
        if self.env.su:
            return
        user = self.env.user
        if user.has_group('campus_pmb.group_pmb') or user.has_group('campus_core.group_campus_administrator'):
            return
        raise AccessError(_("Only PMB staff can accept an application."))

    def action_reject(self):
        self._require_state({'draft', 'submitted', 'document_review'})
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
        unpaid_reg = self.filtered(
            lambda record: record.registration_fee > 0 and not record.registration_fee_paid
        )
        if unpaid_reg:
            raise UserError(_("Registration fee must be paid before accepting an applicant."))
        self._write_state('accepted')
        self.activity_feedback([
            'campus_pmb.mail_activity_type_document_review',
            'campus_pmb.mail_activity_type_payment_verification',
        ])
        for record in self:
            name = record.name or '-'
            record._schedule_pmb_activity(
                'campus_pmb.mail_activity_type_create_account',
                _("Create student portal account and NIM for %s") % name,
            )
            if record.reregistration_fee > 0 and not record.reregistration_fee_paid:
                record._schedule_pmb_activity(
                    'campus_pmb.mail_activity_type_payment_verification',
                    _("Verify re-registration fee payment for %s") % name,
                )

    def action_register(self):
        self._require_state({'accepted'})
        unpaid_reg = self.filtered(
            lambda record: record.registration_fee > 0 and not record.registration_fee_paid
        )
        if unpaid_reg:
            raise UserError(_("Registration fee must be paid before registering a student."))
        unpaid_rereg = self.filtered(
            lambda record: record.reregistration_fee > 0 and not record.reregistration_fee_paid
        )
        if unpaid_rereg:
            raise UserError(_("Re-registration fee must be paid before registering a student."))
        for record in self:
            record._create_account()
            record._write_state('registered')
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

        # Serialize sequence creation per prefix so concurrent first-time requests
        # share one ir.sequence rather than creating duplicate "-0001" series.
        lock_key = zlib.crc32(seq_code.encode('utf-8'))
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))
        seq = self.env['ir.sequence'].sudo().search([('code', '=', seq_code)], limit=1)
        if not seq:
            seq = self.env['ir.sequence'].sudo().create({
                'name': f'NIM Sequence {prefix}',
                'code': seq_code,
                'implementation': 'standard', # Standard is faster and less locking than no_gap
                'prefix': prefix,
                'padding': 4,
                'company_id': False, # Global sequence
            })
        
        # next_by_id() is thread-safe and atomic at the database level
        nim_str = seq.next_by_id()

        return nim_str, batch_year

    def _create_account(self):
        for record in self:
            if record.state not in ('accepted', 'registered'):
                raise UserError(_("Only accepted applicants can have a portal account created."))
            
            if not record.email:
                raise UserError(_("Email is required to create a Portal account."))
                
            if record.user_id:
                raise UserError(_("A portal account has already been created."))
                
            # Case-insensitive exact lookup so mixed-case logins match cleanly.
            email_clean = record.email.strip()
            email_pattern = _escape_like(email_clean)
            existing_user = self.env['res.users'].sudo().search(
                [('login', '=ilike', email_pattern)], limit=1,
            )
            if existing_user:
                if not existing_user.partner_id.is_student:
                    raise UserError(_(
                        "The email %(email)s already belongs to another account in "
                        "the system (%(name)s), which is not a student. Register "
                        "this applicant with a different email address, or ask an "
                        "administrator to resolve the two accounts first."
                    ) % {
                        'email': record.email,
                        'name': existing_user.partner_id.display_name,
                    })
                # Linked rather than created, to avoid the unique-login error.
                record.user_id = existing_user.id
                record.partner_id = existing_user.partner_id.id

                # Update program for re-enrollment while keeping existing permanent NIM.
                update_vals = {'is_student': True, 'program_id': record.program_id.id}
                if not existing_user.partner_id.nim:
                    nim, batch_year = record._generate_nim(record.faculty_id, record.program_id, record.academic_year_id)
                    update_vals.update({
                        'nim': nim,
                        'batch_year': batch_year,
                    })

                existing_user.partner_id.sudo().write(update_vals)
                continue
            
            partner = self.env['res.partner'].sudo().search([
                ('email', '=ilike', email_pattern),
                ('is_student', '=', True),
            ], limit=1)

            # The NIM is drawn only when one is actually going to be written.
            # It used to be generated unconditionally above this block, so every
            # registration that reused an existing student burned a sequence
            # number that was never assigned to anybody, leaving permanent gaps
            # in a campus's enrolment numbering.
            nim = batch_year = None
            if not partner or not partner.nim:
                nim, batch_year = record._generate_nim(
                    record.faculty_id, record.program_id, record.academic_year_id,
                )

            if partner:
                partner_vals = {
                    'name': record.name,
                    'is_student': True,
                    'program_id': record.program_id.id,
                }
                if record.phone:
                    partner_vals['phone'] = record.phone
                if not partner.nim:
                    partner_vals.update({
                        'nim': nim,
                        'batch_year': batch_year,
                    })
                partner.sudo().write(partner_vals)
            else:
                # Create Partner
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
            record.partner_id = partner.id

            # Create User
            portal_group = self.env.ref('base.group_portal')
            
            # NOTE: Password auto-generated from email prefix for demo/onboarding convenience.
            # In production, remove this and use Odoo's built-in 'Reset Password' email flow instead.
            user_password = email_clean.split('@')[0]

            user = self.env['res.users'].sudo().create({
                'name': record.name,
                'login': email_clean,
                'password': user_password,
                'partner_id': partner.id,
                'group_ids': [Command.set([portal_group.id])],
                'company_id': self.env.company.id,
            })
            record.user_id = user.id
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

    @staticmethod
    def _parse_optional_int_id(value):
        if value in (None, False, ''):
            return False
        if isinstance(value, bool):
            raise ValidationError(_("Invalid faculty or program selection."))
        return int(value)

    @api.model
    def _create_admission_from_portal(self, post_data):
        """Create an admission from the public website form.

        The leading underscore is load-bearing. In Odoo 19 any model method
        without one, and without @api.private, can be invoked straight over
        /web/dataset/call_kw by any logged-in user (see
        odoo/service/model.py:get_public_method). Because this method sudo()s,
        a public name let a portal student create admission records despite
        having no ACL on campus.admission at all. Only the controller may call
        this, and only for an anonymous visitor filling in the form.
        """
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

        vals = {
            field: post_data.get(field)
            for field in self._PORTAL_WRITABLE_FIELDS
            if post_data.get(field)
        }
        if not vals.get('name') or not vals.get('email'):
            raise ValidationError(_("Applicant name and email address are required."))
        vals['email'] = vals['email'].strip()

        # A selection value straight off the wire is still untrusted input.
        # Read through the helper, not off the field: the selection is a
        # callable now, so _fields[...].selection is the function itself.
        admission_path = vals.get('admission_path') or 'regular'
        if admission_path not in dict(self._admission_path_selection()):
            raise ValidationError(_("Invalid admission path selection."))
        vals['admission_path'] = admission_path

        # Checked before the insert so a second application with the same email
        # reaches the applicant as "you have already applied" rather than an IntegrityError.
        if vals.get('email') and self.sudo().search_count([
            ('email', '=ilike', _escape_like(vals['email'])),
            ('academic_year_id', '=', active_year.id),
        ]):
            raise ValidationError(_(
                "An application with this email address already exists for this "
                "academic year. Please contact the admissions office if you need "
                "to change it."
            ))

        vals.update({
            'faculty_id': faculty_id,
            'program_id': program_id,
            'academic_year_id': active_year.id,
            # Server-controlled, never taken from the request. A visitor must not
            # be able to skip submission and document review by posting
            # state=accepted and landing straight in the PMB officer's queue.
            'state': 'draft',
        })
        return self.sudo().create(vals)


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
        selection=lambda self: [('all', 'All Paths')] + self.env['campus.admission']._admission_path_selection(),
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
        if not self.env.context.get('pmb_skip_lock'):
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
        return super().write(vals)

    def unlink(self):
        self._check_admission_mutable()
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
        selection=lambda self: [('all', 'All Paths')] + self.env['campus.admission']._admission_path_selection(),
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
        'res.currency', compute='_compute_currency_id',
        default=lambda self: self.env.company.currency_id,
    )

    def _compute_currency_id(self):
        default_currency = self.env.company.currency_id
        for record in self:
            record.currency_id = default_currency

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
    def _get_fee_amount(
        self, fee_type, admission_path=None, program=None, rules=None,
    ):
        """Return the configured fee amount for the given type, path, and program.

        Specificity precedence:
        1. Path-specific + Program-specific
        2. Path-specific + All Programs (e.g. Scholarship exemption across programs)
        3. All Paths + Program-specific (e.g. per-Prodi re-registration / UKT fee)
        4. All Paths + All Programs (general campus fallback)
        Pass a pre-fetched ``rules`` recordset to evaluate in memory without
        issuing a query per call.
        """
        allowed_paths = {'all', admission_path} if admission_path else {'all'}
        allowed_programs = {program.id, False} if program else {False}

        if rules is None:
            domain = [
                ('fee_type', '=', fee_type),
                ('admission_path', 'in', list(allowed_paths)),
                ('program_id', 'in', list(allowed_programs)),
            ]
            matching_rules = self.sudo().search(domain)
        else:
            matching_rules = rules.filtered(
                lambda r: r.fee_type == fee_type
                and r.admission_path in allowed_paths
                and (r.program_id.id or False) in allowed_programs
            )
        if not matching_rules:
            return 0.0
        best_rule = max(
            matching_rules,
            key=lambda r: (
                r.admission_path != 'all',
                bool(r.program_id),
            ),
        )
        return best_rule.amount
