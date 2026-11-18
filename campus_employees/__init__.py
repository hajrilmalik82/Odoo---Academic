from . import models
from . import wizard


_PARTNER_JURISDICTION_DOMAIN = (
    "[('is_student', '=', True)]"
    " + user.employee_id._academic_jurisdiction_domain('program_id')"
)


def _apply_partner_jurisdiction_rules(env):
    """Narrow campus_core's Academic Staff partner rules to the officer's jurisdiction."""
    for xmlid in (
        'campus_core.rule_academic_staff_partner_write',
        'campus_core.rule_academic_staff_partner_create',
    ):
        rule = env.ref(xmlid, raise_if_not_found=False)
        if rule:
            rule.sudo().write({'domain_force': _PARTNER_JURISDICTION_DOMAIN})


def post_init_hook(env):
    _apply_partner_jurisdiction_rules(env)
