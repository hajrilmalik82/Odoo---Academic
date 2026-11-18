from odoo import _, api, fields, models
from odoo.exceptions import AccessError


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
    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company,
    )

    _unique_requirement = models.UniqueIndex(
        "(document_type, COALESCE(company_id, 0))",
        "Each Yudisium document type may only be configured once per company.",
    )

    @api.depends('document_type')
    def _compute_name(self):
        types = dict(self.env['campus.thesis.document']._document_type_selection())
        for record in self:
            record.name = types.get(record.document_type, '')


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
    def _default_document_specs(self, company=None):
        """Return [(document_type, required)] favoring company-specific rules."""
        company = company or self.env.company
        requirements = self.env['campus.thesis.requirement'].sudo().search([
            ('company_id', 'in', [company.id, False]),
        ])
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
        specs = {}
        ranks = {}
        for req in requirements:
            rank = bool(req.company_id)
            if req.document_type not in specs or rank >= ranks[req.document_type]:
                specs[req.document_type] = req.required
                ranks[req.document_type] = rank
        return list(specs.items())

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

    def write(self, vals):
        if 'received' in vals and not self.env.su:
            user = self.env.user
            if not (
                user.has_group('campus_core.group_campus_academic_staff')
                or user.has_group('campus_core.group_campus_administrator')
            ):
                raise AccessError(_(
                    "Only Academic Staff or Campus Administrators can verify Yudisium documents."
                ))
        return super().write(vals)
