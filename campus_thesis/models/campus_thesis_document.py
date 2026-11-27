from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .campus_thesis import _STATE_TRANSITION_TOKEN


class CampusThesisRequirement(models.Model):
    """Configurable checklist of Yudisium filing documents."""

    _name = 'campus.thesis.requirement'
    _description = 'Yudisium Document Requirement'
    _order = 'sequence, document_type'

    name = fields.Char(string='Label', compute='_compute_name')
    sequence = fields.Integer(default=10)
    document_type = fields.Selection(
        selection=lambda self: self.env['campus.thesis.document']._document_type_selection(),
        string='Document Type',
        required=True,
    )
    required = fields.Boolean(string='Required', default=True)

    _unique_requirement = models.Constraint(
        'UNIQUE (document_type)',
        "Each Yudisium document type may only be configured once.",
    )

    @api.depends('document_type')
    def _compute_name(self):
        types = dict(self.env['campus.thesis.document']._document_type_selection())
        for record in self:
            record.name = types.get(record.document_type, '')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Keep in-progress Yudisium filing checklists in sync with newly added
        # requirements without mutating the DB inside a failing submit call.
        filing_theses = self.env['campus.thesis'].sudo().search([
            ('state', '=', 'yudisium_docs'),
        ])
        if filing_theses:
            filing_theses._ensure_default_documents()
        return records


class CampusThesisDocument(models.Model):
    """Per-thesis Yudisium document checklist lines."""

    _name = 'campus.thesis.document'
    _description = 'Thesis Yudisium Document Checklist'
    _order = 'thesis_id, document_type'

    @api.model
    def _document_type_selection(self):
        return [
            ('final_manuscript', _('Final Thesis Manuscript')),
            ('library_clearance', _('Library Clearance (Bebas Pustaka)')),
            ('tuition_clearance', _('Finance / Tuition Clearance')),
            ('temporary_transcript', _('Verified Temporary Transcript')),
            ('graduation_photo', _('Official Graduation Photo')),
            ('journal_article', _('Scientific Journal / Publication Draft')),
            ('other', _('Other Document')),
        ]

    @api.model
    def _default_document_specs(self):
        """Return [(document_type, required)] from Yudisium document configuration."""
        requirements = self.env['campus.thesis.requirement'].sudo().search([])
        if not requirements:
            return [
                (doc_type, True)
                for doc_type in (
                    'final_manuscript',
                    'library_clearance',
                    'tuition_clearance',
                    'temporary_transcript',
                )
            ]
        return [(req.document_type, req.required) for req in requirements]

    thesis_id = fields.Many2one(
        'campus.thesis', string='Thesis', required=True, ondelete='cascade', index=True,
    )
    document_type = fields.Selection(
        selection=lambda self: self._document_type_selection(),
        string='Document Type',
        required=True,
    )
    required = fields.Boolean(string='Required', default=True)
    submitted_by_student = fields.Boolean(string='Uploaded by Student', default=False)
    received = fields.Boolean(string='Verified / Received', default=False)
    attachment = fields.Binary(string='File Attachment', attachment=True)
    attachment_filename = fields.Char(string='File Name')
    note = fields.Char(string='Note')

    _unique_document_type_per_thesis = models.UniqueIndex(
        "(thesis_id, document_type)",
        "Each Yudisium document type can only appear once per thesis.",
    )

    _LOCKED_THESIS_STATES = {
        'yudisium_supervisor',
        'yudisium_advisor',
        'yudisium_dean',
        'graduated',
        'cancelled',
    }

    def _check_thesis_mutable(self):
        if self.env.context.get('_thesis_state_token') is _STATE_TRANSITION_TOKEN:
            return
        frozen = self.filtered(lambda line: line.thesis_id.state in self._LOCKED_THESIS_STATES)
        if frozen:
            raise ValidationError(_(
                "Yudisium documents are locked once sequential Yudisium approval has begun or the thesis is finalized."
            ))

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('_thesis_state_token') is not _STATE_TRANSITION_TOKEN:
            thesis_ids = {vals['thesis_id'] for vals in vals_list if vals.get('thesis_id')}
            if thesis_ids:
                frozen = self.env['campus.thesis'].browse(list(thesis_ids)).filtered(
                    lambda thesis: thesis.state in self._LOCKED_THESIS_STATES
                )
                if frozen:
                    raise ValidationError(_(
                        "Yudisium documents cannot be added once sequential Yudisium approval has begun or the thesis is finalized."
                    ))
        return super().create(vals_list)

    def _is_admin(self):
        return self.env.su or self.env.user.has_group('campus_core.group_campus_administrator')

    def write(self, vals):
        self._check_thesis_mutable()
        is_workflow = self.env.context.get('_thesis_state_token') is _STATE_TRANSITION_TOKEN
        if 'required' in vals and not is_workflow and not self._is_admin():
            raise AccessError(_(
                "Only Campus Administrators can change whether a Yudisium document is required."
            ))
        if 'thesis_id' in vals:
            target = (
                self.env['campus.thesis'].browse(vals['thesis_id'])
                if vals['thesis_id'] else self.env['campus.thesis']
            )
            if not target or target.state in self._LOCKED_THESIS_STATES:
                raise ValidationError(_(
                    "Yudisium documents cannot be moved to a locked or finalized thesis."
                ))
        if 'received' in vals and not self.env.su:
            user = self.env.user
            if not (
                user.has_group('campus_core.group_campus_academic_staff')
                or user.has_group('campus_core.group_campus_administrator')
            ):
                raise AccessError(_(
                    "Only Academic Staff or Campus Administrators can verify Yudisium documents."
                ))
        res = super().write(vals)
        if 'thesis_id' in vals and not self.env.su:
            self.flush_recordset()
            self.check_access('write')
        return res

    def unlink(self):
        self._check_thesis_mutable()
        is_workflow = self.env.context.get('_thesis_state_token') is _STATE_TRANSITION_TOKEN
        if not is_workflow and not self._is_admin() and self.filtered('required'):
            raise AccessError(_(
                "Required Yudisium document checklist lines can only be deleted by Campus Administrators."
            ))
        return super().unlink()
