from odoo import fields, models


class HrEmployee(models.Model):
    """What campus_pmb adds to an employee: a role and a jurisdiction scope.

    The four pmb_* jurisdiction fields that used to live here are gone. They
    were the same four fields campus_employees declared for academic staff,
    written a second time - same booleans, same many2many pair, same onchange,
    same form page. Both sets are now rows on campus.jurisdiction, told apart by
    `scope`, so this module adds one selection value instead of four fields.
    """

    _inherit = 'hr.employee'

    # The role itself, added here rather than listed in campus_employees. The
    # value only means anything once this module is installed: it is what maps
    # an employee onto group_pmb, and it is what the PMB Staff action and menu
    # filter on.
    academic_role = fields.Selection(
        selection_add=[('pmb', 'PMB Staff')], ondelete={'pmb': 'set null'},
    )

    def _academic_role_groups(self):
        """Add the PMB role to the map campus_employees builds.

        super(), not a redefinition, so campus_employees stays unaware of this
        module and _sync_academic_user_role keeps revoking group_pmb when the
        role changes away from 'pmb'.
        """
        groups = super()._academic_role_groups()
        groups['pmb'] = self.env.ref('campus_pmb.group_pmb')
        return groups

    def _pmb_admission_domain(self, program_path='program_id'):
        """Domain for a PMB officer, called from ir.rule.domain_force.

        Goes through the same helper as academic staff, so the two read their
        assignments the same way and cannot drift apart.

        :param program_path: path to academic.program on the target model -
            'program_id' on campus.admission, 'admission_id.program_id' on its
            document checklist.
        """
        return self._jurisdiction_domain('pmb', program_path)


class CampusJurisdiction(models.Model):
    """Add the PMB scope.

    selection_add, so campus_employees never learns this module exists: it owns
    the model, campus_pmb owns its own purpose for it. A third kind of officer
    is one more line here, in whichever module needs it.
    """

    _inherit = 'campus.jurisdiction'

    scope = fields.Selection(
        selection_add=[('pmb', 'Admissions (PMB)')], ondelete={'pmb': 'cascade'},
    )
