from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import SQL


class AcademicClassSchedule(models.Model):
    _name = 'academic.class.schedule'
    _description = 'Academic Class Schedule'
    _check_company_auto = True
    # The model has no `name` column, so _rec_name's default left name_search
    # with nothing to match on and every schedule dropdown returned the whole
    # table whatever was typed. _rec_names_search is what fixed that; _rec_name
    # is deliberately absent. Pointing it at display_name - a compute with no
    # inverse - would make the first quick-create from a schedule dropdown fail
    # with a required-field error on day_of_week and nothing naming _rec_name.
    # display_name itself is computed below.
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
    room_id = fields.Many2one('campus.room', string='Room', required=True, check_company=True, index=True)
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

    def _enrolled_counts(self, exclude_krs=None, states=None):
        """Seats taken, for the whole recordset, in ONE query.

        This is the single definition of "enrolled". It used to be spelled out
        three separate ways, so the figure the validator blocked on and the
        figure shown on screen disagreed.

        Grouped rather than counted per section. Both list views read this for
        every row on the page, so the per-record form issued one COUNT per
        section: 40 classes of 3 sections cost 123 queries to paint one page,
        and the Schedules list cost one per row. Each of those joined
        academic_krs_line to academic_krs on an unindexed column.

        sudo() because a seat count is a capacity figure, not confidential: a
        student has to see a truthful 35 / 40 even though record rules stop them
        reading anyone else's KRS lines.

        :return: {schedule_id: count}, with an entry for every record in self.
        """
        if not self:
            return {}
        # ('state', ...) not ('krs_id.state', ...): academic.krs.line carries a
        # stored copy of the KRS state, so the whole domain stays on one table
        # and the COUNT can use the (schedule_id, state) index instead of
        # joining academic_krs_line to academic_krs on every seat check.
        domain = [
            ('schedule_id', 'in', self.ids),
            ('state', 'in', states or self._ENROLLED_KRS_STATES),
        ]
        if exclude_krs:
            domain.append(('krs_id', 'not in', exclude_krs.ids))
        groups = self.env['academic.krs.line'].sudo()._read_group(
            domain, ['schedule_id'], ['__count'],
        )
        taken = {schedule.id: count for schedule, count in groups}
        return {record.id: taken.get(record.id, 0) for record in self}

    def _enrolled_count(self, exclude_krs=None, states=None):
        """Seats taken in this one section. See _enrolled_counts.

        `states` widens what counts as taking a seat. The default is the strict
        definition used by the submission check; the mass-assign wizard passes
        the draft states too, because it writes schedules onto draft lines and
        would otherwise not see its own earlier run.
        """
        self.ensure_one()
        return self._enrolled_counts(exclude_krs=exclude_krs, states=states)[self.id]

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
        if not self.ids:
            return
        # Flushed first so pending ORM writes are not clobbered by the raw
        # statement, and the table name comes from _table instead of a literal
        # so renaming the model cannot silently disable the lock.
        self.flush_recordset()
        self.env.cr.execute(SQL(
            "UPDATE %s SET write_date = write_date WHERE id IN %s",
            SQL.identifier(self._table), tuple(self.ids),
        ))

    @api.depends('room_capacity', 'class_id.student_line_ids.schedule_id', 'class_id.student_line_ids.state')
    def _compute_capacity_display(self):
        counts = self._enrolled_counts()
        for record in self:
            enrolled = counts.get(record.id, 0)
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
            # "Kelas" was baked into the f-string, so it could never be
            # translated. Everything user-facing goes through _().
            record.display_name = _("Class %(code)s - %(day)s (%(start)s - %(end)s)") % {
                'code': record.class_code,
                'day': day_name,
                'start': start,
                'end': end,
            }

    @api.constrains('day_of_week', 'start_time', 'end_time', 'room_id', 'lecturer_id', 'class_id')
    def _check_schedule_overlap(self):
        """Room and lecturer double-booking, for the whole batch in one query.

        This used to be two searches per record, each joining
        academic_class_schedule to academic_class to read the academic year, so
        importing a 500-section timetable cost a thousand queries. Here the
        candidates for every (year, day) pair in the batch are read once and
        compared in Python. That also closes a real gap: two sections created
        in the same batch were only ever compared against rows already in the
        table, so a single import could place two classes in one room.
        """
        relevant = self.filtered(lambda record: record.day_of_week and record.class_id)
        if not relevant:
            return
        years = relevant.class_id.academic_year_id
        candidates = self.search([
            ('day_of_week', 'in', list(set(relevant.mapped('day_of_week')))),
            ('class_id.academic_year_id', 'in', years.ids),
        ])
        by_slot = {}
        for schedule in candidates:
            key = (schedule.class_id.academic_year_id.id, schedule.day_of_week)
            by_slot.setdefault(key, []).append(schedule)

        for record in relevant:
            key = (record.class_id.academic_year_id.id, record.day_of_week)
            for other in by_slot.get(key, ()):
                if other.id == record.id:
                    continue
                if not (record.start_time < other.end_time and record.end_time > other.start_time):
                    continue
                if record.room_id and other.room_id == record.room_id:
                    raise ValidationError(_("Room overlap detected on %s") % record.display_name)
                if record.lecturer_id and other.lecturer_id == record.lecturer_id:
                    raise ValidationError(_("Lecturer overlap detected on %s") % record.display_name)
