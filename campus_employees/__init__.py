from . import models
from . import wizard


_BASE_PARTNER_DOMAIN = "[('is_student', '=', True)]"
_PARTNER_JURISDICTION_DOMAIN = (
    _BASE_PARTNER_DOMAIN
    + " + user.employee_id._academic_jurisdiction_domain('program_id')"
)
_PARTNER_RULE_XMLIDS = (
    'campus_core.rule_academic_staff_partner_write',
    'campus_core.rule_academic_staff_partner_create',
)


def _set_partner_jurisdiction_rules(env, domain_force):
    """Update campus_core's Academic Staff partner rules and clear the rule cache."""
    updated = False
    for xmlid in _PARTNER_RULE_XMLIDS:
        rule = env.ref(xmlid, raise_if_not_found=False)
        if rule:
            rule.sudo().write({'domain_force': domain_force})
            updated = True
    if updated:
        env.registry.clear_cache()


def post_init_hook(env):
    """Narrow campus_core's Academic Staff partner rules to the officer's jurisdiction."""
    _set_partner_jurisdiction_rules(env, _PARTNER_JURISDICTION_DOMAIN)


def uninstall_hook(env):
    """Restore campus_core's Academic Staff partner rules before removing hr.employee methods."""
    _set_partner_jurisdiction_rules(env, _BASE_PARTNER_DOMAIN)
