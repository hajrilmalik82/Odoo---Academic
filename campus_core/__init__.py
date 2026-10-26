import logging

from . import models
from . import wizard

_logger = logging.getLogger(__name__)

CAMPUS_LANG = 'id_ID'


def _load_campus_translation(env):
    """Make Indonesian available without imposing it.

    The source strings are English and that is what the system shows; the
    Indonesian catalogue is a translation each user turns on for themselves in
    Preferences. Activating the language is what puts it in that list, and what
    makes Odoo import i18n/*.po at all - an inactive language is skipped, so
    without this the option would be absent and the campus would be English
    only, with 674 translated strings sitting unused in the repository.

    This hook used to go further: it wrote lang on every existing user and set
    a default on res.partner. That overrode a choice the module has no business
    making. An administrator working in English had their own account switched
    to Indonesian the moment campus_core was installed, with no setting to
    point at - the only trace was a line in the install log.
    """
    # _activate_lang returns the language whether or not it had to flip active
    # (odoo/addons/base/models/res_lang.py:161-169), and an empty recordset only
    # when the code is not in res.lang at all.
    lang = env['res.lang']._activate_lang(CAMPUS_LANG)
    if not lang:
        _logger.warning("Could not activate %s; only English will be available.", CAMPUS_LANG)
        return

    # Load this module's own catalogue. Odoo imports i18n/<lang>.po for the
    # languages that are ACTIVE when a module's data is read, and id_ID was not
    # active a moment ago - this hook is what just turned it on. Modules
    # installed after campus_core pick their translations up by themselves;
    # campus_core is the one that would otherwise have no Indonesian at all,
    # leaving the menus, the field labels and the three report names untranslated
    # for anyone who does switch.
    env['ir.module.module'].sudo().search([
        ('name', '=', 'campus_core'),
        ('state', 'in', ('installed', 'to install', 'to upgrade')),
    ])._update_translations(filter_lang=CAMPUS_LANG)


def post_init_hook(env):
    _load_campus_translation(env)
