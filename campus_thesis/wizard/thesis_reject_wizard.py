from odoo import _, fields, models
from odoo.exceptions import ValidationError


class CampusThesisRejectWizard(models.TransientModel):
    """Capture a clear reason when a supervisor rejects or returns a Yudisium."""

    _name = 'campus.thesis.reject.wizard'
    _description = 'Thesis Rejection / Return Wizard'

    thesis_id = fields.Many2one(
        'campus.thesis', string='Thesis', required=True, readonly=True,
    )
    mode = fields.Selection([
        ('supervisor_reject', 'Reject Supervision / Proposal'),
        ('yudisium_return', 'Return Yudisium to Filing'),
    ], string='Action Type', required=True, default='supervisor_reject')
    reason = fields.Text(string='Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        cleaned = (self.reason or '').strip()
        if not cleaned:
            raise ValidationError(_("Please provide a non-empty reason."))
        if self.mode == 'yudisium_return':
            self.thesis_id.action_yudisium_return_to_docs(reason=cleaned)
        else:
            self.thesis_id.action_supervisor_reject(reason=cleaned)
        return {'type': 'ir.actions.act_window_close'}
