from odoo import api, fields, models


class AcademicFaculty(models.Model):
    _name = 'academic.faculty'
    _description = 'Academic Faculty'
    _order = 'name'
    _check_company_auto = True

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
                dept = self.env['hr.department'].create({'name': vals['name']})
                vals['department_id'] = dept.id
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if 'name' in vals:
            for faculty in self:
                if faculty.department_id:
                    faculty.department_id.name = faculty.name
        return res


class AcademicProgram(models.Model):
    _name = 'academic.program'
    _description = 'Academic Program'
    _order = 'name'
    _check_company_auto = True

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
                    'parent_id': parent_dept_id
                })
                vals['department_id'] = dept.id
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        for prog in self:
            if prog.department_id:
                if 'name' in vals:
                    prog.department_id.name = prog.name
                if 'faculty_id' in vals:
                    prog.department_id.parent_id = prog.faculty_id.department_id.id if prog.faculty_id.department_id else False
        return res
