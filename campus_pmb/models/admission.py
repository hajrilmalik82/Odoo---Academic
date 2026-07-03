from odoo import _, api, fields, models, Command
from odoo.exceptions import UserError


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
        default=lambda self: _('New'),
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
        'res.partner', string='Student Profile', readonly=True, tracking=True
    )
    user_id = fields.Many2one(
        'res.users', string='Portal User', readonly=True, tracking=True
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
        string='Documents Complete', compute='_compute_document_progress'
    )
    payment_reference = fields.Char(string='Payment Reference', tracking=True)
    payment_date = fields.Date(string='Payment Date', tracking=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('document_review', 'Document Review'),
        ('payment_pending', 'Payment Pending'),
        ('payment_verified', 'Payment Verified'),
        ('accepted', 'Accepted'),
        ('registered', 'Registered'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', tracking=True, index=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    _email_unique = models.Constraint(
        'unique(email)',
        'An admission record already exists for this email address.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('registration_number', 'New') == 'New':
                vals['registration_number'] = (
                    self.env['ir.sequence'].next_by_code('campus.admission') or 'New'
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

    @api.model
    def search_panel_select_multi_range(self, field_name, **kwargs):
        """
        Hotfix for Odoo 19 bug where groupby with select="multi" 
        passes group_domain=None and crashes the ORM AND() function.
        """
        if kwargs.get('group_domain') is None:
            kwargs['group_domain'] = []
        return super().search_panel_select_multi_range(field_name, **kwargs)

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

    def action_verify_documents(self):
        self._require_state({'document_review'})
        for record in self:
            if not record.documents_complete:
                raise UserError(_("All required documents must be received first."))
            record.state = 'payment_pending'

    def action_verify_payment(self):
        self._require_state({'payment_pending'})
        for record in self:
            if not record.payment_reference:
                raise UserError(_("Payment reference is required before payment verification."))
            record.payment_date = record.payment_date or fields.Date.context_today(record)
            record.state = 'payment_verified'

    def action_reject(self):
        for record in self:
            if record.state in ('accepted', 'registered'):
                raise UserError(_("Accepted or registered applications cannot be rejected."))
            record.state = 'rejected'

    def action_accept(self):
        for record in self:
            if record.state != 'payment_verified':
                raise UserError(_("Only payment-verified applications can be accepted."))
            if not (
                self.env.user.has_group('campus_pmb.group_pmb')
                or self.env.user.has_group('base.group_system')
            ):
                raise UserError(_("Only PMB can accept applications."))
            record.state = 'accepted'

    def action_register(self):
        self._require_state({'accepted'})
        for record in self:
            record._create_account()
            record.state = 'registered'

    def _generate_nim(self, faculty_id, program_id):
        """Generate a unique NIM (Student ID Number) based on faculty, program, and year.
        Format: {FACULTY_ABBR}-{PROG_ABBR}-{YY}-{SEQUENCE:04d}
        e.g., TI-IF-26-0001
        """
        current_date = fields.Date.today()
        year_short = current_date.strftime('%y')
        batch_year = current_date.strftime('%Y')

        fac_name = faculty_id.name or 'FA'
        prog_name = program_id.name or 'PR'

        faculty_str = "".join([w[0].upper() for w in fac_name.split() if w.isalpha()])[:2] or "FA"
        program_str = "".join([w[0].upper() for w in prog_name.split() if w.isalpha()])[:2] or "PR"

        prefix = f"{faculty_str}-{program_str}-{year_short}-"
        last_student = self.env['res.partner'].search(
            [('nim', '=like', f'{prefix}%')], order='nim desc', limit=1
        )
        try:
            new_seq = int(last_student.nim.split('-')[-1]) + 1 if last_student and last_student.nim else 1
        except ValueError:
            new_seq = 1

        return f"{prefix}{new_seq:04d}", batch_year

    def _create_account(self):
        for record in self:
            if record.state not in ('accepted', 'registered'):
                raise UserError(_("Only accepted applicants can have a portal account created."))
            
            if not record.email:
                raise UserError(_("Email is required to create a Portal account."))
                
            if record.user_id:
                raise UserError(_("A portal account has already been created."))
                
            # Check if user with this email already exists in the system
            existing_user = self.env['res.users'].search([('login', '=', record.email)], limit=1)
            if existing_user:
                # If exists, just link it to avoid duplicate constraint error
                record.user_id = existing_user.id
                record.partner_id = existing_user.partner_id.id
                
                # Update existing partner if they don't have student info yet
                update_vals = {'is_student': True}
                if not existing_user.partner_id.nim:
                    nim, batch_year = record._generate_nim(record.faculty_id, record.program_id)
                    update_vals.update({
                        'nim': nim,
                        'batch_year': batch_year,
                        'program_id': record.program_id.id,
                    })

                existing_user.partner_id.write(update_vals)
                continue
            
            # Generate NIM using centralized method
            nim, batch_year = record._generate_nim(record.faculty_id, record.program_id)

            # Create Partner
            partner = self.env['res.partner'].create({
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

            user = self.env['res.users'].create({
                'name': record.name,
                'login': record.email,
                'password': user_password,
                'partner_id': partner.id,
                'group_ids': [Command.set([portal_group.id])],
                'company_id': self.env.company.id,
            })
            record.user_id = user.id


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
        'unique(admission_id, document_type)',
        'Each document type can only appear once per admission.',
    )
