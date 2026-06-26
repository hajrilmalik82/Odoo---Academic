from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AcademicSubject(models.Model):
    _name = 'academic.subject'
    _description = 'Academic Subject'
    _order = 'code, name'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code', required=True)
    credits = fields.Integer(string='Credits (SKS)', default=2)
    term_type = fields.Selection([
        ('odd', 'Odd'),
        ('even', 'Even'),
        ('both', 'Both')
    ], string='Term Type', required=True)
    semester = fields.Selection([
        ('1', 'Semester 1'), ('2', 'Semester 2'), 
        ('3', 'Semester 3'), ('4', 'Semester 4'), 
        ('5', 'Semester 5'), ('6', 'Semester 6'), 
        ('7', 'Semester 7'), ('8', 'Semester 8')
    ], string='Semester')
    prerequisite_ids = fields.Many2many(
        'academic.subject',
        'academic_subject_prerequisite_rel',
        'subject_id',
        'prerequisite_id',
        string='Prerequisites',
        domain="[('program_id', '=', program_id)]",
    )
    program_id = fields.Many2one(
        'academic.program', string='Program', required=True
    )
    faculty_id = fields.Many2one(
        'academic.faculty', string='Faculty',
        related='program_id.faculty_id', store=True
    )
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company
    )

    _code_program_unique = models.Constraint(
        'unique(code, program_id)',
        'Subject code must be unique within a program.',
    )

    @api.constrains('credits')
    def _check_credits(self):
        for record in self:
            if record.credits <= 0:
                raise ValidationError(_("Credits must be greater than zero."))

    @api.model
    def search_panel_select_multi_range(self, field_name, **kwargs):
        if kwargs.get('group_domain') is None:
            kwargs['group_domain'] = []
        return super().search_panel_select_multi_range(field_name, **kwargs)


class AcademicYear(models.Model):
    _name = 'academic.year'
    _description = 'Academic Year'
    _order = 'name desc'

    name = fields.Char(string='Name', required=True)
    active = fields.Boolean(string='Active', default=True)
    krs_start_date = fields.Date(string="KRS Start Date")
    krs_end_date = fields.Date(string="KRS End Date")
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company
    )
