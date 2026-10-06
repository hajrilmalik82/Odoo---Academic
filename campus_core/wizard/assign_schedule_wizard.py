from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class AssignScheduleWizard(models.TransientModel):
    _name = 'assign.schedule.wizard'
    _description = 'Mass Assign Schedule Wizard'

    class_id = fields.Many2one('academic.class', string='Class', required=True, readonly=True)
    subject_id = fields.Many2one(related='class_id.subject_id')
    academic_year_id = fields.Many2one(related='class_id.academic_year_id')
    schedule_id = fields.Many2one(
        'academic.class.schedule',
        string='Schedule',
        required=True,
        domain="[('class_id', '=', class_id)]",
    )
    krs_line_ids = fields.Many2many(
        'academic.krs.line',
        string='Students (KRS Lines)',
        domain="[('subject_id', '=', subject_id), ('krs_id.academic_year_id', '=', academic_year_id), ('schedule_id', '=', False)]",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('active_model') == 'academic.class' and self.env.context.get('active_id'):
            res['class_id'] = self.env.context['active_id']
        return res

    def action_assign_schedule(self):
        self.ensure_one()
        if not self.schedule_id:
            raise ValidationError(_("Please select a schedule."))
        if not self.krs_line_ids:
            raise ValidationError(_("Please select at least one student."))
        if self.schedule_id.class_id != self.class_id:
            raise ValidationError(_("Schedule '%(schedule)s' does not belong to class '%(class_name)s'.") % {
                'schedule': self.schedule_id.display_name,
                'class_name': self.class_id.name,
            })

        # Validation pass
        for line in self.krs_line_ids:
            if line.schedule_id:
                raise ValidationError(_("Student %(student)s already has a schedule assigned.") % {'student': line.student_id.name})
            if line.subject_id != self.class_id.subject_id:
                raise ValidationError(_("Student %(student)s's KRS line is for a different subject than this class.") % {'student': line.student_id.name})
            if line.krs_id.academic_year_id != self.class_id.academic_year_id:
                raise ValidationError(_("Student %(student)s's KRS belongs to a different academic year than this class.") % {'student': line.student_id.name})
            if line.krs_id.state not in ('draft', 'revision'):
                raise ValidationError(
                    _("Student %(student)s's KRS is already %(state)s and can no longer be changed.") % {
                        'student': line.student_id.name,
                        'state': line.krs_id.state,
                    }
                )

        # Seat check. This wizard wrote straight through without one, so an
        # administrator could drop two hundred students into a forty-seat room
        # while the KRS form was carefully refusing the forty-first.
        capacity = self.schedule_id.room_capacity
        if capacity <= 0:
            raise ValidationError(
                _("Schedule '%s' has no room capacity set.") % self.schedule_id.display_name
            )
        self.schedule_id._lock_for_enrolment()
        taken = self.schedule_id._enrolled_count()
        if taken + len(self.krs_line_ids) > capacity:
            raise ValidationError(
                _("Not enough seats: %(capacity)s in the room, %(taken)s already taken, "
                  "%(adding)s being assigned.") % {
                    'capacity': capacity,
                    'taken': taken,
                    'adding': len(self.krs_line_ids),
                }
            )

        # Batch write pass (eliminates loop write)
        self.krs_line_ids.write({'schedule_id': self.schedule_id.id})

        return {'type': 'ir.actions.act_window_close'}
