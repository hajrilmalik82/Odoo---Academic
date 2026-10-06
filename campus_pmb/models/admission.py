import logging
import re
from odoo import _, api, fields, models, Command
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)



class CampusAdmission(models.Model):
    _name = 'campus.admission'
    _description = 'New Student Admission'
    _order = 'registration_date desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
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
    admission_path = fields.Selection([
        ('regular', 'Regular'),
        ('scholarship', 'Scholarship'),
        ('transfer', 'Transfer'),
    ], string='Admission Path', default='regular', required=True, tracking=True)

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
    required_document_count = fields.Integer(
        string='Required Documents', compute='_compute_document_progress'
    )
    received_document_count = fields.Integer(
        string='Received Documents', compute='_compute_document_progress'
    )
    documents_complete = fields.Boolean(
        string='Documents Complete', compute='_compute_document_progress', tracking=True
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

    # NOTE: this is case-sensitive, so Budi@x.com and budi@x.com are still two
    # distinct applications. Normalising the email on write is tracked
    # separately; see the audit checklist.
    _email_year_unique = models.Constraint(
        'UNIQUE (email, academic_year_id)',
        "An admission record already exists for this email in this academic year.",
    )

    @api.model
    def search_panel_select_multi_range(self, field_name, **kwargs):
        """See academic.subject for why: Odoo 19 crashes on group_domain=None.

        This model's search panel groups program_id by faculty, which is exactly
        the configuration that triggers it.
        """
        if kwargs.get('group_domain') is None:
            kwargs['group_domain'] = []
        return super().search_panel_select_multi_range(field_name, **kwargs)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('registration_number', 'New') == 'New':
                vals['registration_number'] = (
                    self.env['ir.sequence'].sudo().next_by_code('campus.admission') or 'New'
                )
        records = super().create(vals_list)
        for record in records:
            record._ensure_default_documents()
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
        default_documents = self.env['campus.admission.document']._default_document_types()
        for record in self:
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

    def _require_state(self, allowed_states):
        for record in self:
            if record.state not in allowed_states:
                raise UserError(_(
                    "This action is not allowed from the current admission status."
                ))

    def action_submit(self):
        for record in self:
            if record.state != 'draft':
                raise UserError(_("Only draft applications can be submitted."))
            record._ensure_default_documents()
            record.state = 'submitted'

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

    def _do_accept(self):
        """The single path into the 'accepted' state.

        There used to be two buttons doing this, and only one of them checked
        the group, so the check was effectively dead: any internal user with
        write access could accept an applicant through the other one. Both the
        duplicate method and its button are gone.
        """
        self._require_state({'document_review'})
        self._check_may_accept()
        for record in self:
            if not record.documents_complete:
                raise UserError(_("All required documents must be received first."))
        self.write({'state': 'accepted'})

    def action_reject(self):
        for record in self:
            if record.state in ('accepted', 'registered'):
                raise UserError(_("Accepted or registered applications cannot be rejected."))
            record.state = 'rejected'

    def action_accept(self):
        self._do_accept()

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

        fac_name = faculty_id.name or 'FA'
        prog_name = program_id.name or 'PR'

        faculty_str = "".join([w[0].upper() for w in fac_name.split() if w.isalpha()])[:2] or "FA"
        program_str = "".join([w[0].upper() for w in prog_name.split() if w.isalpha()])[:2] or "PR"

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
            
            # Generate NIM using centralized method
            nim, batch_year = record._generate_nim(record.faculty_id, record.program_id, record.academic_year_id)

            # Check if partner exists (e.g. created by finance module via invoice)
            partner = self.env['res.partner'].sudo().search([('email', '=', record.email)], limit=1)
            
            if partner:
                partner.sudo().write({
                    'name': record.name,
                    'phone': record.phone,
                    'is_student': True,
                    'nim': nim,
                    'batch_year': batch_year,
                    'program_id': record.program_id.id,
                })
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

        if program_id:
            program = self.env['academic.program'].sudo().browse(program_id)
            if faculty_id and program.faculty_id.id != faculty_id:
                raise ValidationError(_("Program does not belong to the selected faculty."))
            if not faculty_id:
                faculty_id = program.faculty_id.id

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
        admission_path = vals.get('admission_path') or 'regular'
        if admission_path not in dict(self._fields['admission_path'].selection):
            raise ValidationError(_("Invalid admission path selection."))
        vals['admission_path'] = admission_path

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


class CampusAdmissionDocument(models.Model):
    _name = 'campus.admission.document'
    _description = 'Admission Document Checklist'
    _order = 'admission_id, document_type'

    @api.model
    def _default_document_types(self):
        return ['identity_card', 'family_card', 'diploma', 'photo']

    admission_id = fields.Many2one(
        'campus.admission', string='Admission', required=True, ondelete='cascade'
    )
    document_type = fields.Selection([
        ('identity_card', 'Identity Card'),
        ('family_card', 'Family Card'),
        ('diploma', 'Diploma or Graduation Letter'),
        ('photo', 'Photo'),
        ('transcript', 'Transcript'),
        ('other', 'Other'),
    ], string='Document Type', required=True)
    required = fields.Boolean(string='Required', default=True)
    received = fields.Boolean(string='Received')
    note = fields.Char(string='Note')

    _unique_document_type_per_admission = models.Constraint(
        'UNIQUE (admission_id, document_type)',
        "Each document type can only appear once per admission.",
    )
