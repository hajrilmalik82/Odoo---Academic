from odoo import _, api, fields, models


from odoo.osv import expression

class ResPartner(models.Model):
    _inherit = 'res.partner'

    # A plain UNIQUE(nim, company_id) would be ineffective: PostgreSQL treats
    # NULLs as distinct, and res.partner.company_id is NULL for most partners,
    # so duplicate NIMs would still slip through. COALESCE puts every
    # company-less partner in one bucket, and the WHERE clause keeps the many
    # non-student partners (nim IS NULL) out of the index entirely.
    _check_nim_unique = models.UniqueIndex(
        "(nim, COALESCE(company_id, 0)) WHERE nim IS NOT NULL",
        "Student ID (NIM) must be unique!",
    )

    is_student = fields.Boolean(string="Is a Student", default=False, index=True)
    nim = fields.Char(string="Student ID (NIM)")
    
    academic_advisor_id = fields.Many2one(
        'hr.employee', 
        string="Academic Advisor"
    )
    program_id = fields.Many2one('academic.program', string="Study Program")
    faculty_id = fields.Many2one('academic.faculty', related='program_id.faculty_id', string="Faculty", store=True)
    student_status = fields.Selection([
        ('active', 'Active'),
        ('leave', 'On Leave'),
        ('graduated', 'Graduated'),
        ('dropout', 'Drop Out')
    ], default='active', string="Student Status", index=True)
    batch_year = fields.Char(string="Batch / Generation")

    khs_ids = fields.One2many(
        'academic.khs', 'student_id', string='KHS Records'
    )
    cgpa = fields.Float(
        string='CGPA', compute='_compute_cgpa', store=True,
        digits=(5, 2), readonly=True
    )

    @api.depends('khs_ids.total_grade_points', 'khs_ids.graded_credits')
    def _compute_cgpa(self):
        """Average over graded subjects only.

        The denominator is graded_credits, not total_credits: subjects a
        lecturer has not marked yet must not count as zeros, or a student's
        CGPA collapses the moment a new semester's KHS is generated.
        """
        for record in self:
            graded_credits = sum(khs.graded_credits for khs in record.khs_ids)
            total_grade_points = sum(khs.total_grade_points for khs in record.khs_ids)
            record.cgpa = total_grade_points / graded_credits if graded_credits > 0 else 0.0

    @api.depends('name')
    @api.depends_context('display_nim')
    def _compute_display_name(self):
        super()._compute_display_name()
        if self.env.context.get('display_nim'):
            for partner in self:
                if partner.nim:
                    partner.display_name = partner.nim

    @api.model
    def _search_display_name(self, operator, value):
        # Odoo 17+ menggunakan _search_display_name alih-alih _name_search
        domain = super()._search_display_name(operator, value)
        # Gabungkan pencarian default (nama, email, ref) dengan pencarian NIM
        if value:
            return expression.OR([domain, [('nim', operator, value)]])
        return domain
