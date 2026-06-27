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
    semester = fields.Selection([
        ('1', 'Semester 1'), ('2', 'Semester 2'), 
        ('3', 'Semester 3'), ('4', 'Semester 4'), 
        ('5', 'Semester 5'), ('6', 'Semester 6'), 
        ('7', 'Semester 7'), ('8', 'Semester 8'),
        ('9', 'Semester 9'), ('10', 'Semester 10'),
        ('11', 'Semester 11'), ('12', 'Semester 12'),
        ('13', 'Semester 13'), ('14', 'Semester 14')
    ], string='Current Semester')

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
