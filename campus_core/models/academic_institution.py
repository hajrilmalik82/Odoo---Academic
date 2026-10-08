from odoo import _, api, fields, models
from odoo.exceptions import UserError


def _drop_linked_departments(departments):
    """Remove the HR departments that mirrored the deleted academic records.

    Must run after super().unlink(): department_id is ondelete='restrict', so
    the department can only go once the row pointing at it is gone.

    Deleting a faculty or a programme used to leave its department behind, and
    the HR Departments list slowly filled with entries for faculties and
    programmes that no longer existed, several of them sharing a name.

    Refuses while people are still assigned. hr.version.department_id is
    ON DELETE SET NULL, so removing an occupied department would quietly strip
    the department from every employee in it and leave nothing behind to say
    what it used to be.
    """
    if not departments:
        return
    occupied = departments.filtered('member_ids')
    if occupied:
        raise UserError(_(
            "Cannot delete %(names)s: employees are still assigned to the "
            "linked HR department. Move them to another department first."
        ) % {
            'names': ', '.join(occupied.mapped('name')),
        })
    departments.unlink()


class AcademicFaculty(models.Model):
    _name = 'academic.faculty'
    _description = 'Academic Faculty'
    _order = 'name'
    _check_company_auto = True

    # Kept global (not scoped by company_id) to preserve the previous semantics.
    # See audit item S-07 before making this per-company.
    _check_name_unique = models.Constraint(
        'UNIQUE (name)',
        "Faculty name must be unique!",
    )

    name = fields.Char(string='Name', required=True)
    dean_id = fields.Many2one('hr.employee', string="Head of Faculty / Dean", check_company=True)
    department_id = fields.Many2one('hr.department', string="Linked HR Department", ondelete='restrict', copy=False)
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'name' in vals and not vals.get('department_id'):
                dept = self.env['hr.department'].create({
                    'name': vals['name'],
                    'manager_id': vals.get('dean_id', False)
                })
                vals['department_id'] = dept.id
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        for faculty in self:
            if not faculty.department_id:
                continue
            if 'name' in vals:
                faculty.department_id.name = faculty.name
            # Only ever push a real dean onto the department. hr.department.write()
            # reacts to manager_id by rewriting parent_id on every employee of the
            # department (_update_employee_manager in addons/hr), so writing False
            # here stripped the manager from everyone in the faculty merely because
            # the Dean field had been cleared.
            if 'dean_id' in vals and faculty.dean_id:
                faculty.department_id.manager_id = faculty.dean_id.id
                programs = self.env['academic.program'].search([('faculty_id', '=', faculty.id)])
                for program in programs:
                    program._set_head_reports_to(faculty.dean_id)
        return res

    def unlink(self):
        departments = self.department_id
        res = super().unlink()
        _drop_linked_departments(departments)
        return res


class AcademicProgram(models.Model):
    _name = 'academic.program'
    _description = 'Academic Program'
    _order = 'name'
    _check_company_auto = True

    # Global, not scoped by faculty. A programme name identifies the programme
    # across the whole institution: "Teknik Informatika" belongs to exactly one
    # faculty, and the same name appearing under two faculties is a data-entry
    # mistake rather than a legitimate second programme. Scoped by faculty, the
    # constraint accepted those duplicates, and they then showed up twice in the
    # HR department tree with no way to tell them apart.
    # Kept company-wide for the same reason as academic.faculty above.
    _check_name_unique = models.Constraint(
        'UNIQUE (name)',
        "Program name must be unique!",
    )

    name = fields.Char(string='Name', required=True)
    faculty_id = fields.Many2one(
        'academic.faculty', string='Faculty', required=True, check_company=True
    )
    head_id = fields.Many2one('hr.employee', string="Head of Program", check_company=True)
    department_id = fields.Many2one('hr.department', string="Linked HR Department", ondelete='restrict', copy=False)
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'name' in vals and not vals.get('department_id'):
                parent_dept_id = False
                if vals.get('faculty_id'):
                    faculty = self.env['academic.faculty'].browse(vals['faculty_id'])
                    parent_dept_id = faculty.department_id.id if faculty.department_id else False
                dept = self.env['hr.department'].create({
                    'name': vals['name'],
                    'parent_id': parent_dept_id,
                    'manager_id': vals.get('head_id', False)
                })
                vals['department_id'] = dept.id
        programs = super().create(vals_list)
        for program in programs:
            program._set_head_reports_to(program.faculty_id.dean_id)
        return programs

    def _set_head_reports_to(self, dean):
        """Point the programme head at the dean, unless they are the same person.

        hr.employee.parent_id carries no recursion guard in Odoo, so making
        someone their own manager goes through silently and leaves a self-loop in
        the org chart. That happens whenever a dean also heads one of their own
        faculty's programmes, which is ordinary at a small campus.
        """
        self.ensure_one()
        if self.head_id and dean and self.head_id != dean:
            self.head_id.parent_id = dean.id

    def write(self, vals):
        res = super().write(vals)
        for program in self:
            if not program.department_id:
                continue
            if 'name' in vals:
                program.department_id.name = program.name
            # Same reason as on the faculty: writing a blank manager_id would make
            # hr.department strip parent_id from every employee of this programme.
            if 'head_id' in vals and program.head_id:
                program.department_id.manager_id = program.head_id.id
                program._set_head_reports_to(program.faculty_id.dean_id)
            if 'faculty_id' in vals:
                program.department_id.parent_id = program.faculty_id.department_id.id if program.faculty_id.department_id else False
        return res

    def unlink(self):
        departments = self.department_id
        res = super().unlink()
        _drop_linked_departments(departments)
        return res
