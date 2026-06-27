from odoo import _, api, fields, models, Command
from odoo.exceptions import ValidationError


class AcademicKhs(models.Model):
    _name = 'academic.khs'
    _description = 'Academic Transcript (KHS)'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True

    name = fields.Char(string='KHS Number', required=True, copy=False, readonly=True, default=lambda self: 'New')
    student_id = fields.Many2one('res.partner', string='Student', required=True, domain=[('is_student', '=', True)], check_company=True)
    academic_year_id = fields.Many2one('academic.year', string='Academic Year', required=True, check_company=True)
    semester = fields.Char(string='Semester', compute='_compute_semester', store=True)

    @api.depends('academic_year_id')
    def _compute_semester(self):
        for record in self:
            if record.academic_year_id:
                record.semester = record.academic_year_id.name
            else:
                record.semester = False
    line_ids = fields.One2many('academic.khs.line', 'khs_id', string='Grade Lines')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    # Computed GPA fields
    total_credits = fields.Integer(string='Total Credits', compute='_compute_term_gpa', store=True)
    total_grade_points = fields.Float(string='Total Grade Points', compute='_compute_term_gpa', store=True, digits=(16, 2))
    term_gpa = fields.Float(string='Term GPA', compute='_compute_term_gpa', store=True, digits=(5, 2))

    _sql_constraints = [
        ('unique_khs', 
        'unique(student_id, academic_year_id)', 
        'A student can only have one KHS per Academic Year!'),
    ]

    @api.depends('line_ids.grade_points', 'line_ids.credits')
    def _compute_term_gpa(self):
        for record in self:
            total_credits = sum(line.credits for line in record.line_ids)
            total_grade_points = sum(line.credits * line.grade_points for line in record.line_ids)
            record.total_credits = total_credits
            record.total_grade_points = total_grade_points
            record.term_gpa = total_grade_points / total_credits if total_credits > 0 else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('academic.khs') or 'New'
        return super().create(vals_list)

    @api.constrains('student_id', 'academic_year_id')
    def _check_unique_khs(self):
        for record in self:
            if not record.student_id or not record.academic_year_id:
                continue
                
            domain = [
                ('student_id', '=', record.student_id.id),
                ('academic_year_id', '=', record.academic_year_id.id),
                ('id', '!=', record.id)
            ]
            approved_krs = self.env['academic.krs'].search_count([
                ('student_id', '=', record.student_id.id),
                ('academic_year_id', '=', record.academic_year_id.id),
                ('state', 'in', ('approved', 'locked')),
            ])
            if not approved_krs:
                raise ValidationError(
                    _("An approved KRS is required before creating a KHS for this academic period.")
                )

    @api.onchange('student_id', 'academic_year_id')
    def _onchange_student_year(self):
        if self.student_id and self.academic_year_id:
            krs = self.env['academic.krs'].search([
                ('student_id', '=', self.student_id.id),
                ('academic_year_id', '=', self.academic_year_id.id),
                ('state', 'in', ['approved', 'locked'])
            ], limit=1)

            lines = [Command.clear()]

            if krs:
                for line in krs.line_ids:
                    lines.append(Command.create({
                        'subject_id': line.subject_id.id,
                    }))
                self.line_ids = lines
            else:
                self.line_ids = False
                return {
                    'warning': {
                        'title': _("Approved KRS Not Found"),
                        'message': _("No approved KRS found for this student in the selected academic period."),
                    }
                }


class AcademicKhsLine(models.Model):
    _name = 'academic.khs.line'
    _description = 'KHS Grade Line'
    _grade_scale = (
        (80, 'A', 4.00),
        (75, 'A-', 3.75),
        (70, 'B+', 3.50),
        (65, 'B', 3.00),
        (60, 'B-', 2.75),
        (55, 'C+', 2.50),
        (50, 'C', 2.00),
        (40, 'D', 1.00),
        (0, 'E', 0.00),
    )

    khs_id = fields.Many2one('academic.khs', string='KHS', ondelete='cascade')
    subject_id = fields.Many2one('academic.subject', string='Subject', required=True)
    credits = fields.Integer(string='Credits', related='subject_id.credits', store=True)
    schedule_ids = fields.Many2many('academic.class.schedule', string='Schedules')
    # Input field
    numeric_grade = fields.Float(string='Numeric Grade', digits=(5, 2))
    # Computed grade conversion fields
    letter_grade = fields.Char(string='Letter Grade', compute='_compute_grade_conversion', store=True)
    grade_points = fields.Float(string='Grade Points', compute='_compute_grade_conversion', store=True, digits=(5, 2))

    _unique_khs_subject = models.Constraint(
        'unique(khs_id, subject_id)',
        'The same subject cannot appear more than once in a KHS.',
    )
    _numeric_grade_range = models.Constraint(
        'CHECK(numeric_grade >= 0 AND numeric_grade <= 100)',
        'Numeric grade must be between 0 and 100.'
    )

    @api.model
    def _get_grade_from_score(self, score):
        for minimum_score, letter, points in self._grade_scale:
            if score >= minimum_score:
                return letter, points
        return 'E', 0.0

    @api.depends('numeric_grade')
    def _compute_grade_conversion(self):
        for record in self:
            score = record.numeric_grade or 0.0
            letter, points = self._get_grade_from_score(score)
            record.letter_grade = letter
            record.grade_points = points
