from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    academic_role = fields.Selection(string="Academic Role", related="job_id.academic_role", store=True, readonly=True)
    nidn = fields.Char(string="NIDN (Nomor Induk Dosen Nasional)")
    academic_rank = fields.Selection([
        ('asisten_ahli', 'Asisten Ahli'),
        ('lektor', 'Lektor'),
        ('lektor_kepala', 'Lektor Kepala'),
        ('guru_besar', 'Guru Besar')
    ], string="Academic Rank")
    faculty_id = fields.Many2one('academic.faculty', string="Faculty")
    program_id = fields.Many2one(
        'academic.program', 
        string="Program", 
        domain="[('faculty_id', '=', faculty_id)]"
    )

    # PMB Row-Level Security Wewenang (Jurisdiction)
    pmb_faculty_ids = fields.Many2many(
        'academic.faculty', 
        'hr_employee_pmb_faculty_rel', 
        string="PMB Assigned Faculties",
        help="If empty, it means no restriction by faculty (can access all, or restricted by program)."
    )
    pmb_program_ids = fields.Many2many(
        'academic.program', 
        'hr_employee_pmb_program_rel', 
        string="PMB Assigned Programs",
        domain="[('faculty_id', 'in', pmb_faculty_ids)]",
        help="If empty, it means no restriction by program."
    )

    # Academic Staff Row-Level Security Wewenang (Jurisdiction)
    academic_faculty_ids = fields.Many2many(
        'academic.faculty', 
        'hr_employee_academic_faculty_rel', 
        string="Academic Assigned Faculties",
        help="If empty, it means no restriction by faculty (can access all, or restricted by program)."
    )
    academic_program_ids = fields.Many2many(
        'academic.program', 
        'hr_employee_academic_program_rel', 
        string="Academic Assigned Programs",
        domain="[('faculty_id', 'in', academic_faculty_ids)]",
        help="If empty, it means no restriction by program."
    )
