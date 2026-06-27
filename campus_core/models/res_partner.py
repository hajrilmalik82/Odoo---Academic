from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_student = fields.Boolean(string="Is a Student", default=False, index=True)
    nim = fields.Char(string="Student ID (NIM)")
    
    academic_advisor_id = fields.Many2one('hr.employee', string="Academic Advisor")
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

    @api.depends('khs_ids.total_grade_points', 'khs_ids.total_credits')
    def _compute_cgpa(self):
        for record in self:
            total_credits = sum(khs.total_credits for khs in record.khs_ids)
            total_grade_points = sum(khs.total_grade_points for khs in record.khs_ids)
            record.cgpa = total_grade_points / total_credits if total_credits > 0 else 0.0

    @api.depends('name', 'nim')
    def _compute_display_name(self):
        super()._compute_display_name()
        for partner in self:
            if self.env.context.get('display_nim') and partner.nim:
                partner.display_name = partner.nim

    @api.model
    def _name_search(self, name, domain=None, operator='ilike', limit=None, order=None):
        domain = domain or []
        if name:
            domain = ['|', ('name', operator, name), ('nim', operator, name)] + domain
        return self._search(domain, limit=limit, order=order)
