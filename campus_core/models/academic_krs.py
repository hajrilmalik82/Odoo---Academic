from odoo import _, api, fields, models, Command
from odoo.exceptions import ValidationError


class AcademicCoursePackage(models.Model):
    _name = 'academic.course.package'
    _description = 'Academic Course Package'

    name = fields.Char(string='Name', required=True)
    program_id = fields.Many2one('academic.program', string='Program', required=True)
    term_type = fields.Selection([('odd', 'Odd'), ('even', 'Even')], string='Term Type', required=True)
    academic_year_id = fields.Many2one('academic.year', string='Academic Year', required=True)
    total_credits = fields.Integer(string='Total Credits', compute='_compute_total_credits', store=True)
    line_ids = fields.One2many('academic.course.package.line', 'package_id', string='Lines')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('line_ids.credits')
    def _compute_total_credits(self):
        for record in self:
            record.total_credits = sum(record.line_ids.mapped('credits'))


class AcademicCoursePackageLine(models.Model):
    _name = 'academic.course.package.line'
    _description = 'Academic Course Package Line'

    package_id = fields.Many2one('academic.course.package', string='Package', ondelete='cascade')
    subject_id = fields.Many2one('academic.subject', string='Subject', required=True)
    credits = fields.Integer(related='subject_id.credits', string='Credits')

    _unique_subject_per_package = models.Constraint(
        'unique(package_id, subject_id)',
        'A subject can only appear once in a course package.',
    )


class AcademicKrs(models.Model):
    _name = 'academic.krs'
    _description = 'Academic KRS'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True

    name = fields.Char(string='KRS Number', required=True, copy=False, readonly=True, default=lambda self: 'New')
    student_id = fields.Many2one('res.partner', string='Student', required=True, domain=[('is_student', '=', True)], check_company=True)
    academic_year_id = fields.Many2one('academic.year', string='Academic Year', required=True, check_company=True)
    semester = fields.Selection([
        ('1', 'Semester 1'), ('2', 'Semester 2'), 
        ('3', 'Semester 3'), ('4', 'Semester 4'), 
        ('5', 'Semester 5'), ('6', 'Semester 6'), 
        ('7', 'Semester 7'), ('8', 'Semester 8'),
        ('9', 'Semester 9'), ('10', 'Semester 10'),
        ('11', 'Semester 11'), ('12', 'Semester 12'),
        ('13', 'Semester 13'), ('14', 'Semester 14')
    ], string='Semester', required=True, default='1')
    term_type = fields.Selection([('odd', 'Odd'), ('even', 'Even')], string='Term Type', required=True, index=True)
    
    advisor_id = fields.Many2one('hr.employee', related='student_id.academic_advisor_id', string='Academic Advisor', readonly=True)
    program_id = fields.Many2one('academic.program', related='student_id.program_id', string='Study Program', readonly=True)
    
    package_id = fields.Many2one('academic.course.package', string='Course Package')
    state = fields.Selection([
        ('draft', 'Draft'), 
        ('submitted', 'Waiting for Approval'), 
        ('approved', 'Approved'),
        ('revision', 'Needs Revision'),
        ('rejected', 'Rejected'),
        ('locked', 'Locked')
    ], string='Status', default='draft', group_expand='_expand_states', tracking=True, index=True)
    
    total_credits = fields.Integer(string='Total Credits', compute='_compute_total_credits', store=True)
    line_ids = fields.One2many('academic.krs.line', 'krs_id', string='KRS Lines')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    _unique_student_academic_year_term = models.Constraint(
        'unique(student_id, academic_year_id, term_type)',
        'A student can only have one KRS per academic year and term.',
    )



    @api.model
    def _expand_states(self, states, domain, order):
        return [key for key, val in type(self).state.selection]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('academic.krs') or 'New'
        return super().create(vals_list)

    @api.depends('line_ids.credits')
    def _compute_total_credits(self):
        for record in self:
            record.total_credits = sum(record.line_ids.mapped('credits'))

    def _get_max_credits_allowed(self):
        self.ensure_one()
        cgpa = self.student_id.cgpa or 0.0
        if cgpa >= 3.0:
            return 24
        if cgpa >= 2.5:
            return 21
        if cgpa >= 2.0:
            return 18
        return 15

    def _get_class_capacity(self, class_record):
        capacities = [
            capacity for capacity in class_record.schedule_ids.mapped('room_capacity') if capacity
        ]
        return min(capacities) if capacities else 0

    def _check_locked_write_allowed(self, vals):
        protected_fields = {
            'student_id',
            'academic_year_id',
            'term_type',
            'package_id',
            'line_ids',
        }
        if protected_fields.intersection(vals):
            locked_records = self.filtered(lambda record: record.state == 'locked')
            if locked_records:
                raise ValidationError(_("Locked KRS records cannot be modified."))

    def write(self, vals):
        self._check_locked_write_allowed(vals)
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda record: record.state == 'locked'):
            raise ValidationError(_("Locked KRS records cannot be deleted."))
        return super().unlink()

    def action_submit(self):
        for record in self:
            if record.state not in ('draft', 'revision'):
                raise ValidationError(_("Only draft or revision KRS records can be submitted."))
            if not record.line_ids:
                raise ValidationError(_("Please add at least one class before submitting the KRS."))
                
            # 1. Student Status
            if record.student_id.student_status != 'active':
                raise ValidationError(_("Student status must be active to submit a KRS."))
                
            # 2. Period Open
            today = fields.Date.context_today(self)
            if not record.academic_year_id.krs_start_date or not record.academic_year_id.krs_end_date:
                raise ValidationError(_("Academic year KRS period is not configured."))
            if not (record.academic_year_id.krs_start_date <= today <= record.academic_year_id.krs_end_date):
                raise ValidationError(_("Current date is outside the allowed KRS period."))
                
            # 3. Has Advisor (Admin can bypass)
            if not record.advisor_id and not self.env.user.has_group('campus_core.group_campus_administrator'):
                raise ValidationError(_("The student must have an assigned Academic Advisor."))
                
            # 4. Max SKS Limit based on current CGPA.
            max_credits = record._get_max_credits_allowed()
            if record.total_credits > max_credits:
                raise ValidationError(
                    _("Total credits cannot exceed %(max_credits)s SKS for this student.") % {
                        'max_credits': max_credits,
                    }
                )
                
            # Pre-fetch all subjects this student has passed (grade_points >= 2.0)
            # to avoid N+1 queries when checking prerequisites
            passed_subject_ids = set(
                self.env['academic.khs.line'].search([
                    ('khs_id.student_id', '=', record.student_id.id),
                    ('grade_points', '>=', 2.0),
                ]).mapped('subject_id.id')
            )

            # Validate Line constraints
            taken_subjects = []
            schedules = []
            
            for line in record.line_ids:
                subject = line.subject_id
                
                # 5. Subject Matches Program
                if subject.program_id and record.program_id and subject.program_id != record.program_id:
                    raise ValidationError(_("Subject '%s' does not belong to the student's program.") % subject.name)
                    
                # 6. No Duplicate Subjects
                if subject.id in taken_subjects:
                    raise ValidationError(_("Student cannot take the same subject '%s' twice in one KRS.") % subject.name)
                taken_subjects.append(subject.id)
                
                # 7. Prerequisites Met (using pre-fetched data)
                missing_prerequisites = subject.prerequisite_ids.filtered(
                    lambda prerequisite: prerequisite.id not in passed_subject_ids
                )
                if missing_prerequisites:
                    raise ValidationError(
                        _("Missing prerequisite(s) for %(subject)s: %(prerequisites)s") % {
                            'subject': subject.name,
                            'prerequisites': ', '.join(missing_prerequisites.mapped('name')),
                        }
                    )
                
                # 8. Class Quota
                class_record = line.class_id
                total_capacity = record._get_class_capacity(class_record)
                if total_capacity <= 0:
                    raise ValidationError(
                        _("Class '%s' must have at least one scheduled room with capacity.") %
                        class_record.name
                    )
                enrolled_students = len(class_record.student_line_ids)
                if enrolled_students >= total_capacity:
                    raise ValidationError(_("Class '%s' has reached its maximum capacity.") % class_record.name)
                    
                # Collect schedules for overlap check
                for sched in class_record.schedule_ids:
                    schedules.append({
                        'day': sched.day_of_week,
                        'start': sched.start_time,
                        'end': sched.end_time,
                        'name': f"{class_record.name} - {dict(sched._fields['day_of_week'].selection).get(sched.day_of_week)} {sched.start_time}-{sched.end_time}"
                    })
                    
            # 9. No Schedule Overlap
            for i, s1 in enumerate(schedules):
                for s2 in schedules[i + 1:]:
                    if s1['day'] == s2['day']:
                        if s1['start'] < s2['end'] and s1['end'] > s2['start']:
                            raise ValidationError(_("Schedule overlap detected between:\n%s\n%s") % (s1['name'], s2['name']))

            record.state = 'submitted'

    def action_approve(self):
        for record in self:
            if record.state != 'submitted':
                raise ValidationError(_("Only submitted KRS records can be approved."))
            
            # Security
            user = self.env.user
            if record.advisor_id not in user.employee_ids and not user.has_group('campus_core.group_campus_administrator'):
                raise ValidationError(_("Only the assigned Academic Advisor or Academic Admin can approve this KRS."))
                
            # Class Enrollment — batch search + batch create
            class_ids = record.line_ids.mapped('class_id').ids
            existing_class_ids = set(
                self.env['academic.class.student.line'].search([
                    ('class_id', 'in', class_ids),
                    ('student_id', '=', record.student_id.id),
                ]).mapped('class_id.id')
            )
            to_create = [
                {
                    'class_id': line.class_id.id,
                    'student_id': record.student_id.id,
                    'schedule_ids': [(4, line.schedule_id.id)],
                }
                for line in record.line_ids
                if line.class_id.id not in existing_class_ids
            ]
            # Set state to approved FIRST so the class constraint passes
            record.state = 'approved'
            
            if to_create:
                self.env['academic.class.student.line'].create(to_create)

    def action_request_revision(self):
        for record in self:
            if record.state != 'submitted':
                raise ValidationError(_("Only submitted KRS records can be sent for revision."))
            record.state = 'revision'

    def action_reject(self):
        for record in self:
            if record.state != 'submitted':
                raise ValidationError(_("Only submitted KRS records can be rejected."))
            record.state = 'rejected'

    def action_lock(self):
        for record in self:
            if record.state != 'approved':
                raise ValidationError(_("Only approved KRS records can be locked."))
            record.state = 'locked'
            
            # Auto-generate KHS
            existing_khs = self.env['academic.khs'].search([
                ('student_id', '=', record.student_id.id),
                ('academic_year_id', '=', record.academic_year_id.id),
                ('term_type', '=', record.term_type)
            ], limit=1)
            
            if not existing_khs:
                khs_lines = []
                for krs_line in record.line_ids:
                    khs_lines.append((0, 0, {
                        'subject_id': krs_line.subject_id.id,
                        'credits': krs_line.credits,
                        # grade and grade_points will be set by the lecturer later
                    }))
                    
                self.env['academic.khs'].create({
                    'student_id': record.student_id.id,
                    'academic_year_id': record.academic_year_id.id,
                    'term_type': record.term_type,
                    'semester': record.semester,
                    'line_ids': khs_lines,
                })

    def action_set_draft(self):
        for record in self:
            if record.state == 'locked':
                raise ValidationError(_("Locked KRS records cannot be reset to draft."))
            if record.state == 'approved' and not self.env.user.has_group('campus_core.group_campus_administrator'):
                raise ValidationError(_("Only campus administrators can reset an approved KRS to draft."))
            record.state = 'draft'


class AcademicKrsLine(models.Model):
    _name = 'academic.krs.line'
    _description = 'Academic KRS Line'

    krs_id = fields.Many2one('academic.krs', string='KRS', ondelete='cascade')
    schedule_id = fields.Many2one('academic.class.schedule', string='Schedule', required=True)
    class_id = fields.Many2one(related='schedule_id.class_id', store=True)
    subject_id = fields.Many2one('academic.subject', string='Subject', compute='_compute_subject_id', store=True, readonly=False)
    credits = fields.Integer(related='subject_id.credits', string='Credits', store=True)

    @api.depends('schedule_id')
    def _compute_subject_id(self):
        for record in self:
            if record.schedule_id:
                record.subject_id = record.schedule_id.class_id.subject_id

    @api.onchange('subject_id')
    def _onchange_subject_id(self):
        if self.subject_id and self.schedule_id and self.schedule_id.class_id.subject_id != self.subject_id:
            self.schedule_id = False

    _unique_class_per_krs = models.Constraint(
        'unique(krs_id, class_id)',
        'A class can only appear once in the same KRS.'
    )

    def write(self, vals):
        if self.filtered(lambda line: line.krs_id.state == 'locked'):
            raise ValidationError(_("Locked KRS lines cannot be modified."))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda line: line.krs_id.state == 'locked'):
            raise ValidationError(_("Locked KRS lines cannot be deleted."))
        return super().unlink()
