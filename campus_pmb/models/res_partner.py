from odoo import _, api, fields, models


class ResPartner(models.Model):
    """The admission a student arrived through.

    campus_core knows nothing about admissions - campus_pmb depends on it, not
    the other way - so the counter and its button are declared here and grafted
    onto the two student forms that campus_core owns.
    """

    _inherit = 'res.partner'

    admission_ids = fields.One2many(
        'campus.admission', 'partner_id', string="Admissions")
    admission_count = fields.Integer(
        string="Admissions", compute='_compute_admission_count')

    @api.depends('admission_ids')
    def _compute_admission_count(self):
        for partner in self:
            partner.admission_count = len(partner.admission_ids)

    def action_open_admissions(self):
        """No creation. An admission is where a student comes FROM: it is
        opened on the public site or by the admissions desk, and accepting it is
        what creates this contact. Making one from the contact would invert the
        order the NIM and the programme depend on."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Admissions"),
            'res_model': 'campus.admission',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': dict(self.env.context, create=False),
        }
