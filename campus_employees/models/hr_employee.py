from odoo import _, api, fields, models, Command
from odoo.exceptions import AccessError


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

    @api.onchange('department_id')
    def _onchange_department_id_sync_manager(self):
        if self.department_id:
            dept_manager = self.department_id.manager_id
            # If there's a manager and it's NOT the current employee
            if dept_manager and dept_manager._origin.id != self._origin.id:
                self.parent_id = dept_manager
            # If this employee IS the manager, their boss is the parent department's manager (e.g. Dean)
            elif dept_manager and dept_manager._origin.id == self._origin.id:
                if self.department_id.parent_id and self.department_id.parent_id.manager_id:
                    self.parent_id = self.department_id.parent_id.manager_id
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

    # NOTE: the PMB jurisdiction fields (pmb_all_faculties, pmb_faculty_ids,
    # pmb_all_programs, pmb_program_ids) now live in campus_pmb, beside the
    # record rule that reads them. Declaring them here forced this module to
    # depend on campus_pmb while campus_pmb already depended on it.

    # Academic Staff Row-Level Security Wewenang (Jurisdiction)
    academic_all_faculties = fields.Boolean("All Faculties")
    academic_faculty_ids = fields.Many2many(
        'academic.faculty', 
        'hr_employee_academic_faculty_rel', 
        string="Academic Assigned Faculties",
        help="If empty, it means no restriction by faculty (can access all, or restricted by program)."
    )
    academic_all_programs = fields.Boolean("All Programs")
    academic_program_ids = fields.Many2many(
        'academic.program', 
        'hr_employee_academic_program_rel', 
        string="Academic Assigned Programs",
        domain="[('faculty_id', 'in', academic_faculty_ids)]",
        help="If empty, it means no restriction by program."
    )

    @api.onchange('academic_all_faculties')
    def _onchange_academic_all_faculties(self):
        if self.academic_all_faculties:
            self.academic_all_programs = True

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        # Only employees that actually carry a role need syncing. A new employee
        # without one has no campus groups to grant or strip, and running the
        # sync anyway would make ordinary HR hiring hit the administrator check
        # whenever the linked user happened to hold a leftover campus group.
        employees.filtered('academic_role')._sync_academic_user_role()
        return employees

    def write(self, vals):
        res = super().write(vals)
        if 'academic_role' in vals or 'user_id' in vals:
            self._sync_academic_user_role()
        return res

    def _check_may_grant_academic_groups(self):
        """Campus group membership stays an administrator's decision.

        _sync_academic_user_role grants those groups through sudo(), and that
        sudo is precisely what normally stops a non-administrator touching
        group_ids. Odoo gives hr.group_hr_user full write on hr.employee, so
        without this check an HR officer could set academic_role on their own
        employee record and hand themselves group_campus_academic_staff, which
        carries full CRUD on every academic model and on res.partner, delete
        included.
        """
        if self.env.su or self.env.user.has_group('campus_core.group_campus_administrator'):
            return
        raise AccessError(_(
            "Only a Campus Administrator can change an employee's Academic Role, "
            "because it grants campus access groups."
        ))

    def _sync_academic_user_role(self):
        # Fetch groups safely outside the loop
        lecturer_group = self.env.ref('campus_core.group_campus_lecturer')
        academic_staff_group = self.env.ref('campus_core.group_campus_academic_staff')
        pmb_group = self.env.ref('campus_pmb.group_pmb', raise_if_not_found=False)

        academic_groups = lecturer_group | academic_staff_group
        if pmb_group:
            academic_groups |= pmb_group

        role_groups = {
            'lecturer': lecturer_group,
            'academic': academic_staff_group,
        }
        if pmb_group:
            role_groups['pmb'] = pmb_group

        empty = self.env['res.groups']
        for emp in self:
            if not emp.user_id:
                continue

            keep = role_groups.get(emp.academic_role) or empty
            # Read under sudo: this is a comparison, and an ordinary user is not
            # entitled to read another user's group membership.
            current = emp.user_id.sudo().group_ids
            to_add = keep - current
            to_remove = (academic_groups - keep) & current

            # Nothing to change: stay silent. create() runs this for every new
            # employee, so raising unconditionally would stop HR officers
            # creating ordinary staff at all.
            if not to_add and not to_remove:
                continue

            self._check_may_grant_academic_groups()
            emp.user_id.sudo().write({
                'group_ids': [Command.unlink(group.id) for group in to_remove]
                             + [Command.link(group.id) for group in to_add],
            })

class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    academic_role = fields.Selection(related='employee_id.academic_role', readonly=True, store=True)
    nidn = fields.Char(related='employee_id.nidn', readonly=True, store=True)
    academic_rank = fields.Selection(related='employee_id.academic_rank', readonly=True)
    faculty_id = fields.Many2one(related='employee_id.faculty_id', readonly=True)
    program_id = fields.Many2one(related='employee_id.program_id', readonly=True)

    # The pmb_* mirrors moved to campus_pmb alongside their source fields.

    academic_all_faculties = fields.Boolean(related='employee_id.academic_all_faculties', readonly=True)
    academic_faculty_ids = fields.Many2many(related='employee_id.academic_faculty_ids', readonly=True)
    academic_all_programs = fields.Boolean(related='employee_id.academic_all_programs', readonly=True)
    academic_program_ids = fields.Many2many(related='employee_id.academic_program_ids', readonly=True)
