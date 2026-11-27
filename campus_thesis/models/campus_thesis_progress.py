from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

# Unforgeable per-process sentinel ensuring supervisor review status/audit
# fields are only mutated through _set_review_state() (action_approve /
# action_request_revision), never by raw RPC write().
_PROGRESS_REVIEW_TOKEN = object()


class CampusThesisProgress(models.Model):
    """Guidance and progress milestones logged during Proposal and Thesis stages."""

    _name = 'campus.thesis.progress'
    _description = 'Thesis Guidance & Progress Log'
    _order = 'date desc, id desc'

    thesis_id = fields.Many2one(
        'campus.thesis', string='Thesis', required=True, ondelete='cascade', index=True,
    )
    stage = fields.Selection([
        ('proposal', 'Proposal Stage'),
        ('thesis', 'Thesis Stage'),
    ], string='Stage', required=True, default='proposal')
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    milestone = fields.Char(string='Milestone / Chapter', required=True)
    description = fields.Text(string='Guidance Notes', required=True)
    progress_percent = fields.Float(string='Progress (%)', digits=(5, 2), default=0.0)
    attachment = fields.Binary(string='Draft / Attachment', attachment=True)
    attachment_filename = fields.Char(string='File Name')
    state = fields.Selection([
        ('submitted', 'Waiting Review'),
        ('approved', 'Approved'),
        ('revision', 'Needs Revision'),
    ], string='Review Status', default='submitted', required=True, copy=False)
    supervisor_note = fields.Text(string='Supervisor Feedback')
    reviewed_by_id = fields.Many2one('hr.employee', string='Reviewed By', readonly=True)
    reviewed_date = fields.Datetime(string='Reviewed Date', readonly=True)

    _progress_percent_range = models.Constraint(
        'CHECK (progress_percent >= 0 AND progress_percent <= 100)',
        "Progress percentage must be between 0 and 100.",
    )

    def _is_supervisor_or_admin(self, thesis):
        """Return whether the current user is an assigned supervisor or Campus Admin."""
        if self.env.su or self.env.user.has_group('campus_core.group_campus_administrator'):
            return True
        supervisors = thesis.supervisor_id | thesis.co_supervisor_id
        return self.env.user in supervisors.mapped('user_id')

    def _check_supervisor_review_permission(self):
        for line in self:
            if not line._is_supervisor_or_admin(line.thesis_id):
                raise AccessError(_(
                    "Only the assigned Thesis Supervisor(s) or Campus Administrator can review guidance logs."
                ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            thesis_id = vals.get('thesis_id')
            stage = vals.get('stage', 'proposal')
            thesis = self.env['campus.thesis'].browse(thesis_id) if thesis_id else self.env['campus.thesis']
            if thesis and not self._is_supervisor_or_admin(thesis):
                raise AccessError(_(
                    "Only the assigned Thesis Supervisor(s) or Campus Administrator may create progress logs."
                ))
            if thesis and thesis.state != stage:
                raise ValidationError(_(
                    "Cannot log %(stage)s progress while the thesis is in '%(state)s' status.",
                    stage=stage,
                    state=thesis.state,
                ))
        return super().create(vals_list)

    _SUPERVISOR_WRITABLE_FIELDS = {'supervisor_note'}
    _REVIEW_WORKFLOW_FIELDS = {'state', 'reviewed_by_id', 'reviewed_date'}

    def write(self, vals):
        is_admin = self.env.su or self.env.user.has_group('campus_core.group_campus_administrator')
        is_review = self.env.context.get('_progress_review_token') is _PROGRESS_REVIEW_TOKEN
        if not is_admin:
            self._check_supervisor_review_permission()
            allowed = (
                self._SUPERVISOR_WRITABLE_FIELDS | self._REVIEW_WORKFLOW_FIELDS
                if is_review
                else self._SUPERVISOR_WRITABLE_FIELDS
            )
            disallowed = set(vals) - allowed
            if disallowed:
                raise AccessError(_(
                    "Supervisors can only update feedback or use the Approve/Revise buttons, not edit log fields (%s)."
                ) % ', '.join(sorted(disallowed)))
        if not self.env.su:
            for line in self:
                if line.thesis_id.state not in ('proposal', 'thesis'):
                    raise ValidationError(_(
                        "Guidance progress logs can only be modified during the Proposal or Thesis stages."
                    ))
                if line.thesis_id.state != line.stage:
                    raise ValidationError(_(
                        "Guidance progress logs from an earlier stage can no longer be modified."
                    ))
        if 'stage' in vals:
            for line in self:
                if line.thesis_id.state != vals['stage']:
                    raise ValidationError(_(
                        "Progress log stage must match the current thesis stage."
                    ))
        return super().write(vals)

    def _set_review_state(self, new_state):
        """Record supervisor review decision, reviewer, and timestamp."""
        self._check_supervisor_review_permission()
        for line in self:
            if line.thesis_id.state not in ('proposal', 'thesis'):
                raise ValidationError(_(
                    "Guidance progress logs can only be reviewed during the Proposal or Thesis stages."
                ))
            if line.thesis_id.state != line.stage:
                raise ValidationError(_(
                    "Guidance progress logs from an earlier stage can no longer be reviewed."
                ))
        reviewer = self.env.user.employee_id
        self.with_context(_progress_review_token=_PROGRESS_REVIEW_TOKEN).write({
            'state': new_state,
            'reviewed_by_id': reviewer.id if reviewer else False,
            'reviewed_date': fields.Datetime.now(),
        })

    def action_approve(self):
        """Mark the guidance log as approved by the supervisor."""
        self._set_review_state('approved')

    def action_request_revision(self):
        """Return the guidance log to the student for revision."""
        self._set_review_state('revision')
