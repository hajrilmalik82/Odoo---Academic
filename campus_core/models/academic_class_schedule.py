from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AcademicClassSchedule(models.Model):
    _name = 'academic.class.schedule'
    _description = 'Academic Class Schedule'
    _check_company_auto = True
    # The model has no `name` column, so _rec_name's default left name_search
    # with nothing to match on and every schedule dropdown returned the whole
    # table whatever was typed. display_name is computed below.
    _rec_name = 'display_name'
    _rec_names_search = ['class_code', 'class_id.name', 'room_id.name']

    class_id = fields.Many2one('academic.class', string='Class', ondelete='cascade')
    class_program_id = fields.Many2one('academic.program', related='class_id.subject_id.program_id')
    class_faculty_id = fields.Many2one('academic.faculty', related='class_id.subject_id.faculty_id')
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
    # No domain here on purpose. Filtering this to academic lecturers needs
    # academic_role, program_id and faculty_id on hr.employee, and those belong
    # to campus_employees. campus_employees depends on campus_core, so campus_core
    # cannot depend back on it; referencing those fields here made campus_core
    # impossible to install on its own. campus_employees re-applies the domain.
    lecturer_id = fields.Many2one(
        'hr.employee',
        string='Lecturer',
    )
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

    # A seat is only taken once the student's KRS has left their own hands.
    # Draft and rejected plans must not hold places for everyone else.
    _ENROLLED_KRS_STATES = ('submitted', 'approved', 'locked')

    def _enrolled_count(self, exclude_krs=None):
        """Students actually holding a seat in this section.

        This is the single definition of "enrolled". It used to be spelled out
        three separate ways, so the figure the validator blocked on and the
        figure shown on screen disagreed.

        sudo() because a seat count is a capacity figure, not confidential: a
        student has to see a truthful 35 / 40 even though record rules stop them
        reading anyone else's KRS lines.
        """
        self.ensure_one()
        domain = [
            ('schedule_id', '=', self.id),
            ('krs_id.state', 'in', self._ENROLLED_KRS_STATES),
        ]
        if exclude_krs:
            domain.append(('krs_id', 'not in', exclude_krs.ids))
        return self.env['academic.krs.line'].sudo().search_count(domain)

    def _lock_for_enrolment(self):
        """Serialize concurrent enrolment into the same sections.

        Counting free seats and then taking one is a check-then-act, so during
        the KRS rush thirty students read the same free seat and all pass.

        A plain SELECT ... FOR UPDATE does not fix it here: Odoo runs on
        REPEATABLE READ (odoo/sql_db.py), so a transaction that waits on the
        lock still counts against its own older snapshot and sees the seat free.
        Touching the row instead makes the second writer fail with a
        serialization error, which Odoo retries on a fresh snapshot
        (odoo/service/model.py, up to 5 attempts).
        """
        if not self:
            return
        self.env.cr.execute(
            "UPDATE academic_class_schedule SET write_date = write_date WHERE id IN %s",
            (tuple(self.ids),),
        )

    @api.depends('room_capacity', 'class_id.student_line_ids.schedule_id', 'class_id.student_line_ids.state')
    def _compute_capacity_display(self):
        for record in self:
            enrolled = record._enrolled_count()
            record.enrolled_count = enrolled
            record.capacity_display = f"{enrolled} / {record.room_capacity}"

    @staticmethod
    def _format_float_time(value):
        """Render a Float hour as HH:MM.

        Carries the minutes properly, so a value such as 23.999 reads 24:00
        rather than the 23:60 the previous formatting produced, and midnight
        reads 00:00 rather than disappearing on a falsy check.
        """
        minutes = round((value or 0.0) * 60)
        return '{:02d}:{:02d}'.format(minutes // 60, minutes % 60)

    @api.depends('class_code', 'day_of_week', 'start_time', 'end_time')
    def _compute_display_name(self):
        day_dict = dict(self._fields['day_of_week'].selection)
        for record in self:
            day_name = day_dict.get(record.day_of_week, '')
            start = self._format_float_time(record.start_time)
            end = self._format_float_time(record.end_time)
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
