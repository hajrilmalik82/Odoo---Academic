from odoo import _, api, fields, models, Command
from odoo.exceptions import AccessError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # 'pmb' is NOT listed here. It is added by campus_pmb through
    # selection_add, together with the action, the menu and the group it maps
    # to. This module must not depend on campus_pmb - campus_pmb depends on it -
    # so a role that only means something once campus_pmb is installed belongs
    # over there. Installed on its own, campus_employees used to offer a PMB
    # Staff role that granted no group and a PMB Staff menu that opened an
    # action that did not exist.
    academic_role = fields.Selection([
        ('lecturer', 'Lecturer'),
        ('academic', 'Academic Staff (TU)')
    ], string="Academic Role", store=True, tracking=True)
    # The label is the acronym alone, the way the credential is actually
    # written on a lecturer's record. Its Indonesian expansion is domain
    # terminology, so it belongs in help text rather than in a msgid that a
    # translator would have nothing to translate.
    nidn = fields.Char(
        string="NIDN",
        help="National lecturer identification number (Nomor Induk Dosen Nasional).",
    )
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

    # Row-level security jurisdiction.
    #
    # One row per purpose, on campus.jurisdiction. This used to be four fields
    # here (academic_*) and four more in campus_pmb (pmb_*) - the same booleans,
    # the same many2many pair, the same onchange and the same form page, written
    # twice. Protection moved with them: campus.jurisdiction is administrator-
    # only in its ACL, including read, which is a stronger and simpler guard
    # than groups= on eight separate fields.
    jurisdiction_ids = fields.One2many(
        'campus.jurisdiction', 'employee_id', string='Jurisdiction',
        help="Which faculties and programmes this employee may reach, per purpose.",
    )

    # --- onchange ---------------------------------------------------------
    # Odoo's own ordering convention: every field declaration first, then the
    # onchange methods. These two used to sit in the middle of the field list.

    @api.onchange('job_id')
    def _onchange_job_id_academic(self):
        # Assigned unconditionally: the job position decides the campus role.
        # Setting it only when the new position carried one left the previous
        # value behind, so moving an employee from a lecturer position to an
        # ordinary one kept academic_role at 'lecturer'. The Lecturer Profile
        # page stayed on a non-academic employee, and saving would have granted
        # them the lecturer group.
        self.academic_role = self.job_id.academic_role or False

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

    def _jurisdiction(self, scope):
        """This employee's assignment for one purpose, or an empty recordset.

        sudo() because ir.rule evaluates domain_force as the user themselves
        (ir_rule.py:48 passes env.user), while campus.jurisdiction is
        administrator-only. Reading one's own assignment in order to build
        one's own restriction grants nothing.
        """
        employee = self[:1].sudo()
        if not employee:
            return self.env['campus.jurisdiction']
        return employee.jurisdiction_ids.filtered(lambda row: row.scope == scope)[:1]

    def _jurisdiction_domain(self, scope, program_path):
        """Record-rule domain for one employee and one purpose."""
        return self._jurisdiction(scope)._domain_for(program_path)

    def _academic_jurisdiction_domain(self, program_path='program_id'):
        """Domain for an Academic Staff member, called from ir.rule.domain_force."""
        return self._jurisdiction_domain('academic', program_path)

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

    def _academic_role_groups(self):
        """Map academic_role to the campus group it grants.

        A method, like the jurisdiction scope selection, so campus_pmb can add its own role
        with super() instead of this module reaching across to an xmlid it is
        not allowed to depend on.
        """
        return {
            'lecturer': self.env.ref('campus_core.group_campus_lecturer'),
            'academic': self.env.ref('campus_core.group_campus_academic_staff'),
        }

    def _sync_academic_user_role(self):
        role_groups = self._academic_role_groups()
        # Every group any role can grant: what a role change must take away as
        # well as what it gives.
        academic_groups = self.env['res.groups'].union(*role_groups.values())

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

    # Deliberately not stored, like every other mirror on this model. The parent
    # is an _auto = False model whose table is a SQL view joining hr_employee to
    # hr_version (addons/hr/models/hr_employee_public.py:194-203), and PostgreSQL
    # refuses to update a view built from more than one table. Storing these two
    # folded them into that view's SELECT via _get_fields(), so every write of
    # academic_role or nidn on an existing employee queued a recompute here and
    # died at flush with "cannot update view hr_employee_public", taking the
    # whole transaction with it. Creating an employee happened to survive, which
    # is why the Lecturer and PMB forms looked fine.
    # Nothing is lost by dropping it: fields.py:636-638 grants a non-stored
    # related field its own search, which a stored one on a view never had.
    academic_role = fields.Selection(related='employee_id.academic_role', readonly=True)
    nidn = fields.Char(related='employee_id.nidn', readonly=True)
    academic_rank = fields.Selection(related='employee_id.academic_rank', readonly=True)
    faculty_id = fields.Many2one(related='employee_id.faculty_id', readonly=True)
    program_id = fields.Many2one(related='employee_id.program_id', readonly=True)

    # The pmb_* mirrors moved to campus_pmb alongside their source fields.

    # The four academic_* jurisdiction fields are deliberately NOT mirrored
    # here. They are the access-control map, nothing reads them through
    # hr.employee.public - the record rules go through user.employee_id, and
    # env.user is already sudoed (odoo/orm/environments.py: the `user` cached
    # property returns a su recordset) - and mirroring row-level security
    # configuration onto the model every internal user can read is the wrong
    # default even with a groups= gate on top.
