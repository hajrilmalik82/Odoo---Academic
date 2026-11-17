from odoo import _, fields, models


class HrEmployee(models.Model):
    """Track active thesis supervisions and extend the lecturer move guard."""

    _inherit = 'hr.employee'

    supervised_thesis_count = fields.Integer(
        string='Theses Supervised',
        compute='_compute_supervised_thesis_count',
        compute_sudo=True,
    )

    def _compute_supervised_thesis_count(self):
        for employee in self:
            employee.supervised_thesis_count = 0

        saved = self.browse([eid for eid in self.ids if isinstance(eid, int)])
        if not saved:
            return

        theses = self.env['campus.thesis'].sudo().search([
            ('state', '!=', 'cancelled'),
            '|',
            ('supervisor_id', 'in', saved.ids),
            ('co_supervisor_id', 'in', saved.ids),
        ])
        counts = {}
        for thesis in theses:
            if thesis.supervisor_id.id in saved.ids:
                counts[thesis.supervisor_id.id] = counts.get(thesis.supervisor_id.id, 0) + 1
            if (
                thesis.co_supervisor_id
                and thesis.co_supervisor_id.id in saved.ids
                and thesis.co_supervisor_id != thesis.supervisor_id
            ):
                counts[thesis.co_supervisor_id.id] = counts.get(thesis.co_supervisor_id.id, 0) + 1

        for employee in saved:
            employee.supervised_thesis_count = counts.get(employee.id, 0)

    def _what_still_points_here(self):
        attached = super()._what_still_points_here()
        active_theses = self.env['campus.thesis'].sudo().search([
            ('state', 'not in', ('graduated', 'cancelled')),
            '|',
            ('supervisor_id', '=', self.id),
            ('co_supervisor_id', '=', self.id),
        ])
        if active_theses:
            attached.append(_(
                "Active thesis supervision (%(count)s): %(titles)s",
                count=len(active_theses),
                titles=", ".join(active_theses[:5].mapped('title'))
                       + ("..." if len(active_theses) > 5 else ""),
            ))
        return attached

    def action_open_supervised_theses(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Theses Supervised"),
            'res_model': 'campus.thesis',
            'view_mode': 'list,form',
            'domain': [
                '|',
                ('supervisor_id', '=', self.id),
                ('co_supervisor_id', '=', self.id),
            ],
            'context': dict(self.env.context, create=False),
        }
