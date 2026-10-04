from odoo import api, fields, models


class HrEmployee(models.Model):
    """PMB jurisdiction fields.

    These live here rather than in campus_employees because the PMB record rule
    (campus_pmb/security/pmb_security.xml) reads them. Declaring them in
    campus_employees forced that module to depend on campus_pmb while campus_pmb
    already depended on it, which made the module graph unresolvable.

    The many2many relation table names are stated explicitly and must not change:
    they carry the existing assignments across this move.
    """

    _inherit = 'hr.employee'

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


class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    pmb_all_faculties = fields.Boolean(related='employee_id.pmb_all_faculties', readonly=True)
    pmb_faculty_ids = fields.Many2many(related='employee_id.pmb_faculty_ids', readonly=True)
    pmb_all_programs = fields.Boolean(related='employee_id.pmb_all_programs', readonly=True)
    pmb_program_ids = fields.Many2many(related='employee_id.pmb_program_ids', readonly=True)
