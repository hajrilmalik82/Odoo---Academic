from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


SEMESTER_SELECTION = [
    ('1', 'Semester 1'), ('2', 'Semester 2'),
    ('3', 'Semester 3'), ('4', 'Semester 4'),
    ('5', 'Semester 5'), ('6', 'Semester 6'),
    ('7', 'Semester 7'), ('8', 'Semester 8'),
]


class AcademicSubject(models.Model):
    _name = 'academic.subject'
    _description = 'Academic Subject'
    # The mixin carries the Odoo 19 search-panel workaround, which campus.admission
    # needs too; see campus_mixins.py for what it works around and when to drop it.
    _inherit = ['campus.searchpanel.group.domain.mixin']
    _order = 'code, name'
    _rec_names_search = ['name', 'code']

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code', required=True)
    credits = fields.Integer(string='Credits (SKS)', default=2)
    term_type = fields.Selection([
        ('odd', 'Odd'),
        ('even', 'Even'),
        ('both', 'Both')
    ], string='Term Type', required=True)
    semester = fields.Selection(SEMESTER_SELECTION, string='Semester')
    prerequisite_ids = fields.Many2many(
        'academic.subject',
        'academic_subject_prerequisite_rel',
        'subject_id',
        'prerequisite_id',
        string='Prerequisites',
        domain="[('program_id', '=', program_id)]",
    )
    program_id = fields.Many2one(
        'academic.program', string='Program', required=True,
    )
    faculty_id = fields.Many2one(
        'academic.faculty', string='Faculty',
        related='program_id.faculty_id', store=True
    )

    _code_program_unique = models.Constraint(
        'UNIQUE (code, program_id)',
        "Subject code must be unique within a program.",
    )

    @api.constrains('credits')
    def _check_credits(self):
        for record in self:
            if record.credits <= 0:
                raise ValidationError(_("Credits must be greater than zero."))

    @api.constrains('prerequisite_ids', 'program_id')
    def _check_prerequisite_cycle(self):
        """A subject must not require itself or a prerequisite from another program."""
        if self._has_cycle('prerequisite_ids'):
            raise ValidationError(_(
                "A subject cannot be its own prerequisite, directly or through a chain "
                "of prerequisites."
            ))
        for record in self:
            if not record.program_id:
                continue
            cross_program = record.prerequisite_ids.filtered(
                lambda pre: pre.program_id and pre.program_id != record.program_id
            )
            if cross_program:
                raise ValidationError(_(
                    "Prerequisite '%(pre)s' must belong to the same study program as '%(subject)s'."
                ) % {
                    'pre': cross_program[0].display_name,
                    'subject': record.display_name,
                })


class AcademicYear(models.Model):
    _name = 'academic.year'
    _description = 'Academic Year'
    _order = 'name desc, term_type asc, id desc'

    _name_term_unique = models.Constraint(
        'UNIQUE (name, term_type)',
        "Academic Year with this name and term already exists.",
    )

    name = fields.Char(string='Name', required=True)
    term_type = fields.Selection([('odd', 'Odd'), ('even', 'Even')], string='Term Type', required=True)
    active = fields.Boolean(string='Active', default=True)
    krs_start_date = fields.Date(string="KRS Start Date")
    krs_end_date = fields.Date(string="KRS End Date")

    @api.constrains('krs_start_date', 'krs_end_date')
    def _check_krs_period(self):
        for record in self:
            start, end = record.krs_start_date, record.krs_end_date
            if bool(start) != bool(end):
                raise ValidationError(_(
                    "Both KRS Start Date and KRS End Date must be set together."
                ))
            if start and end and start > end:
                raise ValidationError(_(
                    "The KRS period cannot end before it starts."
                ))

    @api.model
    def _get_krs_period_open(self):
        """The academic year whose KRS registration window covers today."""
        today = fields.Date.context_today(self)
        return self.search([
            ('active', '=', True),
            ('krs_start_date', '<=', today),
            ('krs_end_date', '>=', today),
        ], order='krs_start_date desc, id desc', limit=1)

    @api.model
    def _get_current(self):
        """The academic year the system should treat as current."""
        return self._get_krs_period_open() or self.search(
            [('active', '=', True)], order='name desc, term_type asc, id desc', limit=1,
        )

    @api.depends('name', 'term_type')
    def _compute_display_name(self):
        # _description_selection, not .selection: the raw attribute is the list
        # as written in the source, so the label came out in English even for a
        # user reading the system in Indonesian - including on the printed
        # transcript, where every row said "(Odd)".
        terms = dict(self._fields['term_type']._description_selection(self.env))
        for record in self:
            if record.name and record.term_type:
                record.display_name = f"{record.name} ({terms.get(record.term_type, '')})"
            else:
                record.display_name = record.name or ""
