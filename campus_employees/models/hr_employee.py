from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    academic_role = fields.Selection([
        ('lecturer', 'Lecturer'),
        ('pmb', 'PMB Staff'),
        ('academic', 'Academic Staff (TU)')
    ], string="Academic Role", store=True, tracking=True)

    @api.onchange('job_id')
    def _onchange_job_id_academic(self):
        if self.job_id and self.job_id.academic_role:
            self.academic_role = self.job_id.academic_role
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
    pmb_all_faculties = fields.Boolean("All Faculties")
    pmb_faculty_ids = fields.Many2many(
        'academic.faculty', 
        'hr_employee_pmb_faculty_rel', 
        string="PMB Assigned Faculties",
        help="If empty, it means no restriction by faculty (can access all, or restricted by program)."
    )
    pmb_all_programs = fields.Boolean("All Programs")
    pmb_program_ids = fields.Many2many(
        'academic.program', 
        'hr_employee_pmb_program_rel', 
        string="PMB Assigned Programs",
        domain="[('faculty_id', 'in', pmb_faculty_ids)]",
        help="If empty, it means no restriction by program."
    )

    @api.onchange('pmb_all_faculties')
    def _onchange_pmb_all_faculties(self):
        if self.pmb_all_faculties:
            self.pmb_all_programs = True

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

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        employees._sync_academic_user_role()
        return employees

    def write(self, vals):
        res = super().write(vals)
        if 'academic_role' in vals or 'user_id' in vals:
            self._sync_academic_user_role()
        return res

    def _sync_academic_user_role(self):
        for emp in self:
            if not emp.user_id:
                continue
            
            # Fetch groups safely
            academic_groups = self.env.ref('campus_core.group_campus_lecturer') | \
                              self.env.ref('campus_core.group_campus_academic_staff')
            pmb_group = self.env.ref('campus_pmb.group_pmb', raise_if_not_found=False)
            if pmb_group:
                academic_groups |= pmb_group
                
            new_group = None
            if emp.academic_role == 'lecturer':
                new_group = self.env.ref('campus_core.group_campus_lecturer')
            elif emp.academic_role == 'pmb' and pmb_group:
                new_group = pmb_group
            elif emp.academic_role == 'academic':
                new_group = self.env.ref('campus_core.group_campus_academic_staff')
                
            if new_group:
                groups_to_remove = academic_groups - new_group
                emp.user_id.sudo().write({
                    'group_ids': [(3, g.id) for g in groups_to_remove] + [(4, new_group.id)]
                })
            else:
                emp.user_id.sudo().write({
                    'group_ids': [(3, g.id) for g in academic_groups]
                })
