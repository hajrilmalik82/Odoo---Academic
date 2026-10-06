from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AcademicSubject(models.Model):
    _name = 'academic.subject'
    _description = 'Academic Subject'
    _order = 'code, name'
    _check_company_auto = True

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
        'UNIQUE (code, program_id)',
        "Subject code must be unique within a program.",
    )

    @api.constrains('credits')
    def _check_credits(self):
        for record in self:
            if record.credits <= 0:
                raise ValidationError(_("Credits must be greater than zero."))

    @api.constrains('prerequisite_ids')
    def _check_prerequisite_cycle(self):
        """A subject must not require itself, directly or through a chain.

        prerequisite_ids is a self-referential many2many with no guard, so a
        subject could be made its own prerequisite. KRS submission then rejects
        it forever: the prerequisite can never be passed, because passing it
        requires passing it.
        """
        if self._has_cycle('prerequisite_ids'):
            raise ValidationError(_(
                "A subject cannot be its own prerequisite, directly or through a chain "
                "of prerequisites."
            ))


class AcademicYear(models.Model):
    _name = 'academic.year'
    _description = 'Academic Year'
    _order = 'name desc'
    _check_company_auto = True

    # COALESCE so that two company-less academic years cannot collide
    # (PostgreSQL treats NULL company_id values as distinct).
    _name_term_company_unique = models.UniqueIndex(
        "(name, term_type, COALESCE(company_id, 0))",
        "Academic Year with this name and term already exists for this company.",
    )

    name = fields.Char(string='Name', required=True)
    term_type = fields.Selection([('odd', 'Odd'), ('even', 'Even')], string='Term Type', required=True)
    active = fields.Boolean(string='Active', default=True)
    krs_start_date = fields.Date(string="KRS Start Date")
    krs_end_date = fields.Date(string="KRS End Date")
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company
    )

    @api.constrains('krs_start_date', 'krs_end_date')
    def _check_krs_period(self):
        for record in self:
            start, end = record.krs_start_date, record.krs_end_date
            if start and end and start > end:
                raise ValidationError(_(
                    "The KRS period cannot end before it starts."
                ))

    @api.model
    def _get_krs_period_open(self):
        """The academic year whose KRS registration window covers today.

        Empty when registration is closed, which is a meaningful answer: the
        portal shows "registration is closed" rather than guessing a year.
        """
        today = fields.Date.context_today(self)
        return self.search([
            ('active', '=', True),
            ('krs_start_date', '<=', today),
            ('krs_end_date', '>=', today),
        ], order='krs_start_date desc, id desc', limit=1)

    @api.model
    def _get_current(self):
        """The academic year the system should treat as current.

        One definition, because there were two: campus_pmb took the highest id
        among active years while campus_portal took the one whose KRS period
        covered today, so the two modules could disagree about which year a
        student was being put into.

        Preference goes to the year currently open for registration. Outside any
        registration window it falls back to the most recent active year, so
        admissions still land somewhere sensible between terms.
        """
        return self._get_krs_period_open() or self.search(
            [('active', '=', True)], order='id desc', limit=1,
        )

    @api.depends('name', 'term_type')
    def _compute_display_name(self):
        for record in self:
            if record.name and record.term_type:
                term = dict(self._fields['term_type'].selection).get(record.term_type)
                record.display_name = f"{record.name} ({term})"
            else:
                record.display_name = record.name or ""
