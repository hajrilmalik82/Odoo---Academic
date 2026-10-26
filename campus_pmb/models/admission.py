import logging
import re
from odoo import _, api, fields, models, Command
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)



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
    _check_company_auto = True

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
        'academic.faculty', string='Faculty', required=True, tracking=True, check_company=True
    )
    program_id = fields.Many2one(
        'academic.program', string='Program', required=True, tracking=True, check_company=True,
        domain="[('faculty_id', '=', faculty_id)]"
    )
    academic_year_id = fields.Many2one(
        'academic.year', string='Academic Year', required=True, tracking=True, check_company=True
    )

    partner_id = fields.Many2one(
        'res.partner', string='Student Profile', readonly=True, tracking=True, copy=False
    )
    user_id = fields.Many2one(
        'res.users', string='Portal User', readonly=True, tracking=True, copy=False
    )
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

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('document_review', 'Document Review'),
        ('accepted', 'Accepted'),
        ('registered', 'Registered'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', tracking=True, index=True, copy=False)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

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
                    Command.create({'document_type': document_type, 'required': True})
                    for document_type in Document._default_document_types(
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

    def _ensure_default_documents(self):
        Document = self.env['campus.admission.document']
        for record in self:
            default_documents = Document._default_document_types(record.admission_path)
            existing_types = set(record.document_line_ids.mapped('document_type'))
            lines = [
                Command.create({
                    'document_type': document_type,
                    'required': True,
                })
                for document_type in default_documents
                if document_type not in existing_types
            ]
            if lines:
                record.write({'document_line_ids': lines})

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

    def write(self, vals):
        if 'state' in vals:
            self._check_state_transition_allowed(vals['state'])
        return super().write(vals)

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
        self.write({'state': 'submitted'})

    def action_start_document_review(self):
        self._require_state({'submitted'})
        self.write({'state': 'document_review'})

    def _check_may_accept(self):
        """Accepting an applicant is a PMB decision, not an ordinary edit."""
        if self.env.su:
            return
        user = self.env.user
        if user.has_group('campus_pmb.group_pmb') or user.has_group('campus_core.group_campus_administrator'):
            return
        raise AccessError(_("Only PMB staff can accept an application."))

    def action_reject(self):
        # Spelled as the states it IS allowed from, matching every other
        # transition and the _STATE_TRANSITIONS graph above, rather than as the
        # two it is not.
        self._require_state({'draft', 'submitted', 'document_review', 'rejected'})
        self.write({'state': 'rejected'})

    def action_accept(self):
        """The single path into the 'accepted' state.

        There used to be two buttons doing this, and only one of them checked
        the group, so the check was effectively dead: any internal user with
        write access could accept an applicant through the other one. Both the
        duplicate method and its button are gone, and the remaining button does
        the work itself rather than delegating to a one-line _do_accept() - the
        indirection was the last trace of the pair.

        _check_may_accept stays on THIS path deliberately: accepting an
        applicant is a PMB decision, and the group check is the only thing that
        makes it one.
        """
        self._require_state({'document_review'})
        self._check_may_accept()
        incomplete = self.filtered(lambda record: not record.documents_complete)
        if incomplete:
            raise UserError(_("All required documents must be received first."))
        self.write({'state': 'accepted'})

    def action_register(self):
        self._require_state({'accepted'})
        for record in self:
            record._create_account()
            record.state = 'registered'

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

        # Get or create sequence for this specific prefix dynamically
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
                
            # Check if user with this email already exists in the system
            existing_user = self.env['res.users'].sudo().search([('login', '=', record.email)], limit=1)
            if existing_user:
                # If exists, just link it to avoid duplicate constraint error
                record.user_id = existing_user.id
                record.partner_id = existing_user.partner_id.id
                
                # Update existing partner if they don't have student info yet
                update_vals = {'is_student': True}
                if not existing_user.partner_id.nim:
                    nim, batch_year = record._generate_nim(record.faculty_id, record.program_id, record.academic_year_id)
                    update_vals.update({
                        'nim': nim,
                        'batch_year': batch_year,
                        'program_id': record.program_id.id,
                    })

                existing_user.partner_id.sudo().write(update_vals)
                continue
            
            # Only an existing STUDENT contact is reused. The search used to match
            # any partner sharing the email and overwrite its name and phone, so
            # registering an applicant could rename a vendor, a customer or a
            # finance contact that happened to use the same address. Creating a
            # second contact is the lesser evil: res.partner.email is not unique
            # in Odoo, and renaming someone else's record is not recoverable.
            partner = self.env['res.partner'].sudo().search([
                ('email', '=', record.email),
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
                    'phone': record.phone,
                    'is_student': True,
                }
                # Guarded the same way the existing_user branch above is. A NIM
                # is a permanent identifier: it is on the student's transcript,
                # their card and every KHS already issued. Overwriting one with
                # a fresh sequence value violates no constraint - the unique
                # index only forbids two partners SHARING a NIM - so a student
                # re-registering for a second programme silently acquired a new
                # number and their old documents stopped matching the system.
                if not partner.nim:
                    partner_vals.update({
                        'nim': nim,
                        'batch_year': batch_year,
                        'program_id': record.program_id.id,
                    })
                partner.sudo().write(partner_vals)
            else:
                # Create Partner
                partner = self.env['res.partner'].sudo().create({
                    'name': record.name,
                    'email': record.email,
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
            user_password = record.email.split('@')[0]

            user = self.env['res.users'].sudo().create({
                'name': record.name,
                'login': record.email,
                'password': user_password,
                'partner_id': partner.id,
                'group_ids': [Command.set([portal_group.id])],
                'company_id': self.env.company.id,
            })
            record.user_id = user.id
            _logger.info("Created Portal User and Partner for student NIM: %s (Email: %s)", nim, record.email)

    # The only fields an anonymous website visitor may supply. Everything else on
    # campus.admission is decided by the server. This list is the security
    # boundary for the public /admission/submit route: the request dict must
    # never be passed to create() wholesale, or a visitor could set `state`,
    # `registration_number`, `partner_id` or `user_id` themselves.
    _PORTAL_WRITABLE_FIELDS = ('name', 'email', 'phone', 'previous_school', 'admission_path')

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
            faculty_id = int(post_data.get('faculty_id')) if post_data.get('faculty_id') else False
            program_id = int(post_data.get('program_id')) if post_data.get('program_id') else False
        except (ValueError, TypeError):
            raise ValidationError(_("Invalid faculty or program selection."))

        # exists() before reading. browse() on an id that is not there raises
        # MissingError, whose message names the model, the record id and the
        # internal uid - handed straight to an anonymous visitor by the
        # controller. The faculty was never checked at all.
        company_domain = ['|', ('company_id', '=', False), ('company_id', '=', self.env.company.id)]
        if program_id:
            program = self.env['academic.program'].sudo().search(
                [('id', '=', program_id)] + company_domain, limit=1,
            )
            if not program:
                raise ValidationError(_("Invalid study programme selection."))
            if faculty_id and program.faculty_id.id != faculty_id:
                raise ValidationError(_("Program does not belong to the selected faculty."))
            if not faculty_id:
                faculty_id = program.faculty_id.id
        if faculty_id and not self.env['academic.faculty'].sudo().search_count(
            [('id', '=', faculty_id)] + company_domain,
        ):
            raise ValidationError(_("Invalid faculty selection."))

        # Shared definition, so PMB and the student portal agree on which year
        # is current. This used to be "the highest id among active years", which
        # was arbitrary and could differ from what the portal considered current.
        active_year = self.env['academic.year'].sudo()._get_current()
        if not active_year:
            raise ValidationError(_("No active academic year found for admission."))

        vals = {
            field: post_data.get(field)
            for field in self._PORTAL_WRITABLE_FIELDS
            if post_data.get(field)
        }

        # A selection value straight off the wire is still untrusted input.
        # Read through the helper, not off the field: the selection is a
        # callable now, so _fields[...].selection is the function itself.
        admission_path = vals.get('admission_path') or 'regular'
        if admission_path not in dict(self._admission_path_selection()):
            raise ValidationError(_("Invalid admission path selection."))
        vals['admission_path'] = admission_path

        # Checked before the insert so a second application with the same email
        # reaches the applicant as "you have already applied" rather than as the
        # controller's catch-all "system error" - a UNIQUE violation is a
        # psycopg2 IntegrityError, not a ValidationError, so it fell through to
        # the generic branch. The database constraint stays as the race backstop.
        if vals.get('email') and self.sudo().search_count([
            ('email', '=', vals['email']),
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
    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company,
    )

    _unique_requirement = models.UniqueIndex(
        "(document_type, admission_path, COALESCE(company_id, 0))",
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
    def _default_document_types(self, admission_path=None):
        """The checklist an applicant on this path is asked for.

        Read from campus.admission.requirement, which an administrator can edit,
        rather than from a list written into this method. Falls back to the four
        the module ships only when nothing at all is configured, so a
        half-set-up campus still produces a usable checklist.
        """
        domain = [('admission_path', 'in', ['all', admission_path] if admission_path else ['all'])]
        requirements = self.env['campus.admission.requirement'].sudo().search(domain)
        if requirements:
            return list(dict.fromkeys(requirements.mapped('document_type')))
        return ['identity_card', 'family_card', 'diploma', 'photo']

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
