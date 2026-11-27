from . import models
from . import wizard


_BASE_PARTNER_DOMAIN = "[('is_student', '=', True)]"
_BASE_PARTNER_WRITE_DOMAIN = "['|', ('is_student', '=', True), ('id', '=', user.partner_id.id)]"
_PARTNER_JURISDICTION_DOMAIN = (
    _BASE_PARTNER_DOMAIN
    + " + user.employee_ids._academic_jurisdiction_domain('program_id')"
)
_PARTNER_WRITE_JURISDICTION_DOMAIN = (
    "['|', ('id', '=', user.partner_id.id), '&', ('is_student', '=', True)]"
    " + user.employee_ids._academic_jurisdiction_domain('program_id')"
)
_PARTNER_RULE_XMLIDS = (
    'campus_core.rule_academic_staff_partner_write',
    'campus_core.rule_academic_staff_partner_create',
)
_BASE_DOMAINS_BY_RULE = {
    'campus_core.rule_academic_staff_partner_write': _BASE_PARTNER_WRITE_DOMAIN,
    'campus_core.rule_academic_staff_partner_create': _BASE_PARTNER_DOMAIN,
}
_JURISDICTION_DOMAINS_BY_RULE = {
    'campus_core.rule_academic_staff_partner_write': _PARTNER_WRITE_JURISDICTION_DOMAIN,
    'campus_core.rule_academic_staff_partner_create': _PARTNER_JURISDICTION_DOMAIN,
}


def _apply_partner_rule_domains(env, domain_map):
    """Update campus_core's Academic Staff partner rules and clear the rule cache."""
    updated = False
    for xmlid, domain_force in domain_map.items():
        rule = env.ref(xmlid, raise_if_not_found=False)
        if rule:
            rule.sudo().write({'domain_force': domain_force})
            updated = True
    if updated:
        env.registry.clear_cache()


def post_init_hook(env):
    """Narrow campus_core's Academic Staff partner rules to the officer's jurisdiction."""
    _apply_partner_rule_domains(env, _JURISDICTION_DOMAINS_BY_RULE)


def uninstall_hook(env):
    """Restore campus_core's Academic Staff partner rules before removing hr.employee methods."""
    _apply_partner_rule_domains(env, _BASE_DOMAINS_BY_RULE)
