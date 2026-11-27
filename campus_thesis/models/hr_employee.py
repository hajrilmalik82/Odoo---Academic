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

        saved_ids = list(saved.ids)
        Thesis = self.env['campus.thesis'].sudo()
        counts = {}
        for supervisor, count in Thesis._read_group(
            [('state', '!=', 'cancelled'), ('supervisor_id', 'in', saved_ids)],
            ['supervisor_id'],
            ['__count'],
        ):
            if supervisor:
                counts[supervisor.id] = counts.get(supervisor.id, 0) + count
        for co_sup, count in Thesis._read_group(
            [('state', '!=', 'cancelled'), ('co_supervisor_id', 'in', saved_ids)],
            ['co_supervisor_id'],
            ['__count'],
        ):
            if co_sup:
                counts[co_sup.id] = counts.get(co_sup.id, 0) + count

        for employee in saved:
            employee.supervised_thesis_count = counts.get(employee.id, 0)

    def _what_still_points_by_employee(self):
        by_emp = super()._what_still_points_by_employee()
        if not by_emp:
            return by_emp
        saved_ids = set(by_emp)
        saved_list = list(saved_ids)
        is_unlink = bool(self.env.context.get('_campus_unlink_check'))
        Thesis = self.env['campus.thesis'].sudo()

        domain = [
            '|',
            ('supervisor_id', 'in', saved_list),
            ('co_supervisor_id', 'in', saved_list),
        ]
        if not is_unlink:
            domain = [('state', 'not in', ('graduated', 'cancelled'))] + domain
        theses = Thesis.search(domain)
        titles_by_emp = {}
        for thesis in theses:
            if thesis.supervisor_id.id in saved_ids:
                titles_by_emp.setdefault(thesis.supervisor_id.id, []).append(thesis.title)
            if (
                thesis.co_supervisor_id
                and thesis.co_supervisor_id.id in saved_ids
                and thesis.co_supervisor_id != thesis.supervisor_id
            ):
                titles_by_emp.setdefault(thesis.co_supervisor_id.id, []).append(thesis.title)
        for emp_id, titles in titles_by_emp.items():
            label = (
                _("Thesis supervision history (%(count)s): %(titles)s")
                if is_unlink
                else _("Active thesis supervision (%(count)s): %(titles)s")
            )
            by_emp[emp_id].append(label % {
                'count': len(titles),
                'titles': ", ".join(titles[:5]) + ("..." if len(titles) > 5 else ""),
            })

        if is_unlink:
            signed = Thesis.search([
                '|', '|',
                ('yudisium_supervisor_by_id', 'in', saved_list),
                ('yudisium_advisor_by_id', 'in', saved_list),
                ('yudisium_dean_by_id', 'in', saved_list),
            ])
            signed_by_emp = {}
            for thesis in signed:
                for signer in (
                    thesis.yudisium_supervisor_by_id,
                    thesis.yudisium_advisor_by_id,
                    thesis.yudisium_dean_by_id,
                ):
                    if signer and signer.id in saved_ids:
                        signed_by_emp.setdefault(signer.id, set()).add(thesis.name)
            for emp_id, refs in signed_by_emp.items():
                ordered = sorted(refs)
                by_emp[emp_id].append(_(
                    "Yudisium clearance sign-offs (%(count)s): %(refs)s",
                    count=len(ordered),
                    refs=", ".join(ordered[:5]) + ("..." if len(ordered) > 5 else ""),
                ))
        return by_emp

    def action_open_supervised_theses(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Theses Supervised"),
            'res_model': 'campus.thesis',
            'view_mode': 'list,form',
            'domain': [
                ('state', '!=', 'cancelled'),
                '|',
                ('supervisor_id', '=', self.id),
                ('co_supervisor_id', '=', self.id),
            ],
            'context': dict(self.env.context, create=False),
        }
