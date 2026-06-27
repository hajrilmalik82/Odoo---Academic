from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AcademicClassSchedule(models.Model):
    _name = 'academic.class.schedule'
    _description = 'Academic Class Schedule'
    _check_company_auto = True

    class_id = fields.Many2one('academic.class', string='Class', ondelete='cascade')
    class_code = fields.Char(string='Class Code (A/B/C)', required=True, default="A")
    day_of_week = fields.Selection([
        ('0', 'Monday'),
        ('1', 'Tuesday'),
        ('2', 'Wednesday'),
        ('3', 'Thursday'),
        ('4', 'Friday'),
        ('5', 'Saturday'),
        ('6', 'Sunday')
    ], string='Day of Week', required=True)
    start_time = fields.Float(string='Start Time', required=True)
    end_time = fields.Float(string='End Time', required=True)
    room_id = fields.Many2one('campus.room', string='Room', required=True)
    room_capacity = fields.Integer(related='room_id.capacity', string='Capacity', readonly=True)
    lecturer_id = fields.Many2one('hr.employee', string='Lecturer')
    company_id = fields.Many2one(related='class_id.company_id', store=True)
    enrolled_count = fields.Integer(string='Enrolled', compute='_compute_capacity_display')
    capacity_display = fields.Char(string='Capacity (Max/Filled)', compute='_compute_capacity_display')

    @api.constrains('start_time', 'end_time')
    def _check_time_range(self):
        for record in self:
            if record.start_time < 0 or record.end_time < 0:
                raise ValidationError(_("Schedule times cannot be negative."))
            if record.start_time >= record.end_time:
                raise ValidationError(_("Schedule end time must be after start time."))
            if record.end_time > 24:
                raise ValidationError(_("Schedule end time cannot be later than 24:00."))

    @api.depends('room_capacity', 'class_id.student_line_ids.schedule_id', 'class_id.student_line_ids.state')
    def _compute_capacity_display(self):
        for record in self:
            valid_lines = record.class_id.student_line_ids.filtered(lambda s: s.state in ['submitted', 'approved', 'locked'])
            enrolled = len(valid_lines.filtered(lambda s: s.schedule_id.id == record.id))
            record.enrolled_count = enrolled
            record.capacity_display = f"{record.room_capacity} / {enrolled}"

    def _compute_display_name(self):
        for record in self:
            day_dict = dict(self._fields['day_of_week'].selection)
            day_name = day_dict.get(record.day_of_week, '')
            start = '{0:02d}:{1:02d}'.format(
                int(record.start_time), int(round((record.start_time % 1) * 60))
            ) if record.start_time else ''
            end = '{0:02d}:{1:02d}'.format(
                int(record.end_time), int(round((record.end_time % 1) * 60))
            ) if record.end_time else ''
            record.display_name = f"Kelas {record.class_code} - {day_name} ({start} - {end})"

    @api.constrains('day_of_week', 'start_time', 'end_time', 'room_id', 'lecturer_id', 'class_id')
    def _check_schedule_overlap(self):
        for record in self:
            # Check room overlap
            overlap_room = self.search([
                ('id', '!=', record.id),
                ('room_id', '=', record.room_id.id),
                ('day_of_week', '=', record.day_of_week),
                ('class_id.academic_year_id', '=', record.class_id.academic_year_id.id),
                ('start_time', '<', record.end_time),
                ('end_time', '>', record.start_time),
            ])
            if overlap_room:
                raise ValidationError(_("Room overlap detected on %s") % record.display_name)

            # Check lecturer overlap — skip if no lecturer assigned
            if record.lecturer_id:
                overlap_lecturer = self.search([
                    ('id', '!=', record.id),
                    ('lecturer_id', '=', record.lecturer_id.id),
                    ('day_of_week', '=', record.day_of_week),
                    ('class_id.academic_year_id', '=', record.class_id.academic_year_id.id),
                    ('start_time', '<', record.end_time),
                    ('end_time', '>', record.start_time),
                ])
                if overlap_lecturer:
                    raise ValidationError(_("Lecturer overlap detected on %s") % record.display_name)
