from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class AssignScheduleWizard(models.TransientModel):
    _name = 'assign.schedule.wizard'
    _description = 'Mass Assign Schedule Wizard'

    class_id = fields.Many2one('academic.class', string='Class', required=True, readonly=True)
    schedule_id = fields.Many2one('academic.class.schedule', string='Schedule', required=True)
    
    # We will compute the domain so only students who haven't selected a schedule yet appear.
    krs_line_ids = fields.Many2many(
        'academic.krs.line',
        string='Students (KRS Lines)'
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id and self.env.context.get('active_model') == 'academic.class':
            class_record = self.env['academic.class'].browse(active_id)
            res['class_id'] = active_id
        return res
        
    @api.onchange('class_id')
    def _onchange_class_id(self):
        if self.class_id:
            # Filter krs_line_ids to only those missing a schedule for this subject and academic year
            domain = [
                ('subject_id', '=', self.class_id.subject_id.id),
                ('krs_id.academic_year_id', '=', self.class_id.academic_year_id.id),
                ('schedule_id', '=', False),
                # Optional: Only include submitted/approved/locked students? Or even draft?
                # The user said "yang krs atau subject itu belum memiliki schedule". Let's allow all states.
            ]
            return {'domain': {'krs_line_ids': domain, 'schedule_id': [('class_id', '=', self.class_id.id)]}}

    def action_assign_schedule(self):
        self.ensure_one()
        if not self.schedule_id:
            raise ValidationError(_("Please select a schedule."))
        if not self.krs_line_ids:
            raise ValidationError(_("Please select at least one student."))
            
        for line in self.krs_line_ids:
            if line.schedule_id:
                raise ValidationError(_("Student %(student)s already has a schedule assigned.") % {'student': line.student_id.name})
            line.schedule_id = self.schedule_id.id
            
        return {'type': 'ir.actions.act_window_close'}
