from odoo import _, api, models
from odoo.exceptions import UserError


class HrDepartment(models.Model):
    """Guard the departments that mirror a faculty or a programme.

    academic.faculty and academic.program each keep an hr.department in step
    with them, so the org chart in the Employees app matches the academic
    structure. That sync is one-directional: academic.faculty.write pushes the
    name and the dean across, and nothing reads back. An HR manager renaming the
    mirrored department from the Employees app therefore left the two
    representations disagreeing, with nothing to detect it - and deleting it
    from that side was only stopped by ondelete='restrict', which reports a
    foreign-key error rather than a reason.

    The alternative was to make academic.faculty an _inherits delegate of
    hr.department, which removes the duplication outright. That was weighed and
    turned down: it forces department_id to ondelete='cascade', so deleting a
    department from the Employees app would delete the faculty and every
    programme, class and study plan under it. Trading a maintenance cost for a
    data-loss path is the wrong way round. This guard closes the hole the sync
    actually has, at a twentieth of the risk.
    """

    _inherit = 'hr.department'

    # Fields an academic record owns. Everything else - the manager's own
    # settings, the colour, the company - stays editable from HR.
    _MIRRORED_FIELDS = ('name', 'parent_id', 'manager_id')

    def _academic_owner(self):
        """The faculty or programme mirrored by each department in self.

        :return: {department id: owner record}, only for mirrored departments.
        """
        owners = {}
        for model in ('academic.faculty', 'academic.program'):
            for record in self.env[model].sudo().search([('department_id', 'in', self.ids)]):
                owners[record.department_id.id] = record
        return owners

    def write(self, vals):
        guarded = [name for name in self._MIRRORED_FIELDS if name in vals]
        if guarded and not self.env.context.get('campus_mirror_sync'):
            for department, owner in self._academic_owner().items():
                raise UserError(_(
                    "“%(department)s” mirrors %(owner)s and is kept in step with it. "
                    "Change it in Academic System > Configuration instead; editing it "
                    "here would leave the two disagreeing with nothing to notice."
                ) % {
                    'department': self.browse(department).display_name,
                    'owner': owner.display_name,
                })
        return super().write(vals)

    def unlink(self):
        owners = self._academic_owner()
        if owners and not self.env.context.get('campus_mirror_sync'):
            raise UserError(_(
                "These departments mirror academic records and cannot be deleted "
                "from here: %(names)s. Delete the faculty or programme instead and "
                "its department goes with it."
            ) % {'names': ', '.join(owner.display_name for owner in owners.values())})
        return super().unlink()
