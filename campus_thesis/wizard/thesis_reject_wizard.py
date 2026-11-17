from odoo import fields, models


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
        if self.mode == 'yudisium_return':
            self.thesis_id.action_yudisium_return_to_docs(reason=self.reason)
        else:
            self.thesis_id.action_supervisor_reject(reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
