import logging
from odoo import _, api, fields, models, Command
from odoo.exceptions import ValidationError
from datetime import datetime, time, timedelta
import pytz

_logger = logging.getLogger(__name__)


class AcademicClass(models.Model):
    _name = 'academic.class'
    _description = 'Academic Class'
    _order = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True

    name = fields.Char(string='Class Name', compute='_compute_class_name', store=True, tracking=True)
    subject_id = fields.Many2one('academic.subject', string='Subject', required=True, tracking=True, check_company=True, ondelete='restrict')
    academic_year_id = fields.Many2one('academic.year', string='Academic Year', required=True, tracking=True, check_company=True)
    start_date = fields.Date(string='Start Date', required=True, tracking=True, help="Used as the starting point to generate 14 sessions.")
    class_capacity_display = fields.Char(string='Total Class Capacity', compute='_compute_class_capacity_display')
    schedule_ids = fields.One2many('academic.class.schedule', 'class_id', string='Schedules')
    student_line_ids = fields.One2many('academic.krs.line', 'class_id', string='Students')
    session_ids = fields.One2many('academic.class.session', 'class_id', string='Sessions')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('subject_id', 'academic_year_id')
    def _compute_class_name(self):
        for record in self:
            if record.subject_id and record.academic_year_id:
                record.name = f"{record.subject_id.name} - {record.academic_year_id.name}"
            else:
                record.name = _("New Class")

    @api.depends('schedule_ids.room_capacity', 'student_line_ids', 'student_line_ids.state')
    def _compute_class_capacity_display(self):
        """Seats across every section of this class.

        Capacity is a property of each section's room, so the class total is the
        sum of its sections. It used to be min(), which reported the whole class
        as limited by its smallest room while counting students from all of them.
        """
        for record in self:
            total_capacity = sum(record.schedule_ids.mapped('room_capacity'))
            total_students = sum(
                schedule._enrolled_count() for schedule in record.schedule_ids
            )
            record.class_capacity_display = f"{total_students} / {total_capacity}"

    def action_generate_sessions(self):
        self.ensure_one()
        if not self.start_date:
            raise ValidationError(_("Please set a Start Date to generate sessions."))
        if not self.schedule_ids:
            raise ValidationError(_("Please define at least one schedule to generate sessions."))

        self.session_ids.unlink()

        # Get user's timezone; fall back to UTC if not set
        user_tz = pytz.timezone(self.env.user.tz or 'UTC')

        sessions = []
        for schedule in self.schedule_ids:
            current_date = fields.Date.from_string(self.start_date)
            # Find the first date matching schedule.day_of_week
            # weekday() returns 0 for Monday, 6 for Sunday
            target_weekday = int(schedule.day_of_week)
            days_ahead = target_weekday - current_date.weekday()
            if days_ahead < 0:
                days_ahead += 7
            first_session_date = current_date + timedelta(days=days_ahead)

            for i in range(14):
                session_date = first_session_date + timedelta(weeks=i)

                # Add minutes to midnight instead of building time(hour, minute).
                # A Float hour cannot be fed to time() safely: 24.0 is out of
                # range, and so is anything whose fraction rounds up to 60
                # minutes, such as 23.999 or 8.999. Both used to crash session
                # generation even though _check_time_range accepted them.
                # timedelta also gives the right answer for a class ending at
                # 24:00, which lands on midnight of the following day.
                day_start = datetime.combine(session_date, time())
                local_start_dt = day_start + timedelta(minutes=round(schedule.start_time * 60))
                local_end_dt = day_start + timedelta(minutes=round(schedule.end_time * 60))

                utc_start_dt = user_tz.localize(local_start_dt).astimezone(pytz.utc).replace(tzinfo=None)
                utc_end_dt = user_tz.localize(local_end_dt).astimezone(pytz.utc).replace(tzinfo=None)

                sessions.append(Command.create({
                    'name': f"Session {i + 1}: {self.name}",
                    'start_datetime': utc_start_dt,
                    'end_datetime': utc_end_dt,
                    'room_id': schedule.room_id.id,
                    'lecturer_id': schedule.lecturer_id.id,
                }))

        self.write({'session_ids': sessions})
        _logger.info("Generated %d sessions for class %s", len(sessions), self.name)



class AcademicClassSession(models.Model):
    _name = 'academic.class.session'
    _description = 'Academic Class Session'

    name = fields.Char(string='Name', required=True)
    class_id = fields.Many2one('academic.class', string='Class', ondelete='cascade')
    start_datetime = fields.Datetime(string='Start Datetime', required=True)
    end_datetime = fields.Datetime(string='End Datetime', required=True)
    room_id = fields.Many2one('campus.room', string='Room')
    lecturer_id = fields.Many2one('hr.employee', string='Lecturer')

    @api.constrains('start_datetime', 'end_datetime')
    def _check_session_datetime(self):
        for record in self:
            if (
                record.start_datetime
                and record.end_datetime
                and record.end_datetime <= record.start_datetime
            ):
                raise ValidationError(_("Session end datetime must be after start datetime."))
