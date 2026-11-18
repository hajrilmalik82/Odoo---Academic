from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import SQL


class CampusGraduationSchedule(models.Model):
    """Scheduled graduation ceremony (Wisuda) batches.

    Once a student clears the final Dean approval on Yudisium, the thesis
    workflow looks up the nearest open graduation schedule that still has
    capacity and before its registration deadline, and assigns the student to it.
    """

    _name = 'campus.graduation.schedule'
    _description = 'Graduation Schedule (Wisuda)'
    _order = 'graduation_date asc, id asc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Batch Name', required=True, tracking=True)
    academic_year_id = fields.Many2one(
        'academic.year', string='Academic Year', tracking=True,
    )
    graduation_date = fields.Date(
        string='Graduation Date', required=True, index=True, tracking=True,
    )
    registration_deadline = fields.Date(
        string='Registration Deadline', tracking=True,
        help="Latest date a student completing Yudisium can be assigned to this batch.",
    )
    location = fields.Char(string='Location / Venue', tracking=True)
    quota = fields.Integer(
        string='Participant Quota', default=0, tracking=True,
        help="Maximum participants allowed for this ceremony. Leave 0 for unlimited.",
    )
    state = fields.Selection([
        ('open', 'Open'),
        ('closed', 'Closed'),
        ('completed', 'Completed'),
    ], string='Status', default='open', required=True, tracking=True, index=True)
    thesis_ids = fields.One2many(
        'campus.thesis', 'graduation_id', string='Graduating Theses',
    )
    participant_count = fields.Integer(
        string='Participants', compute='_compute_participant_count', store=True,
    )

    @api.depends('thesis_ids.state')
    def _compute_participant_count(self):
        for record in self:
            record.participant_count = len(
                record.thesis_ids.filtered(lambda thesis: thesis.state != 'cancelled')
            )

    @api.depends('name', 'graduation_date')
    def _compute_display_name(self):
        for record in self:
            if record.graduation_date:
                record.display_name = f"{record.name} ({record.graduation_date})"
            else:
                record.display_name = record.name or ""

    def _lock_for_quota(self):
        """Serialize concurrent batch assignment under PostgreSQL REPEATABLE READ."""
        if not self.ids:
            return
        self.flush_recordset()
        self.env.cr.execute(SQL(
            "UPDATE %s SET write_date = write_date WHERE id IN %s",
            SQL.identifier(self._table), tuple(self.ids),
        ))

    @api.constrains('graduation_date', 'registration_deadline', 'quota')
    def _check_schedule_validity(self):
        for record in self:
            if (
                record.registration_deadline
                and record.graduation_date
                and record.registration_deadline > record.graduation_date
            ):
                raise ValidationError(_(
                    "Registration deadline cannot be after the graduation date."
                ))
            if record.quota < 0:
                raise ValidationError(_("Participant quota cannot be negative."))
            if record.quota > 0 and record.participant_count > record.quota:
                raise ValidationError(_(
                    "Participant quota cannot be lowered below active participants (%s).",
                    record.participant_count,
                ))

    @api.model
    def _get_nearest_schedule(self, as_of=None, lock=False):
        """Return the earliest open graduation schedule accepting graduates."""
        today = as_of or fields.Date.context_today(self)
        candidates = self.search([
            ('state', '=', 'open'),
            ('graduation_date', '>=', today),
        ], order='graduation_date asc, id asc')
        for schedule in candidates:
            if schedule.registration_deadline and schedule.registration_deadline < today:
                continue
            if lock:
                schedule._lock_for_quota()
                schedule.invalidate_recordset(['participant_count'])
            if schedule.quota > 0 and schedule.participant_count >= schedule.quota:
                continue
            return schedule
        return self.browse()

    def action_close(self):
        self.write({'state': 'closed'})

    def action_reopen(self):
        self.write({'state': 'open'})

    def action_complete(self):
        self.write({'state': 'completed'})

    def action_open_participants(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Graduating Students"),
            'res_model': 'campus.thesis',
            'view_mode': 'list,form',
            'domain': [('graduation_id', '=', self.id), ('state', '!=', 'cancelled')],
            'context': dict(self.env.context, create=False),
        }
