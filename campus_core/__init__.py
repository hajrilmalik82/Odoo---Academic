import logging

from . import models
from . import wizard

_logger = logging.getLogger(__name__)

CAMPUS_LANG = 'id_ID'


def _set_campus_language(env):
    """Make Indonesian the language of the system and of its users.

    Until this existed, the screens were Indonesian only by accident: the source
    strings themselves were written in Indonesian, so they rendered that way
    whatever the configured language was. Now that the source is English with an
    Indonesian catalogue - the arrangement Odoo expects - the language has to be
    asked for, or the campus gets an English interface.

    This sets the system and the users. The WEBSITE's language is a separate
    setting and belongs to campus_website, because a frontend page renders in
    the site's language rather than the visitor's.

    Install-time only. An administrator who later adds English back, or switches
    the site to another language, is making a deliberate choice and this must
    not undo it.
    """
    # _activate_lang returns the language whether or not it had to flip active
    # (odoo/addons/base/models/res_lang.py:161-169), and an empty recordset only
    # when the code is not in res.lang at all.
    lang = env['res.lang']._activate_lang(CAMPUS_LANG)
    if not lang:
        _logger.warning("Could not activate %s; the interface stays in English.", CAMPUS_LANG)
        return

    # Existing accounts, including the portal students campus_pmb created
    # before this module was upgraded.
    users = env['res.users'].sudo().search([('lang', '!=', CAMPUS_LANG)])
    if users:
        users.write({'lang': CAMPUS_LANG})
        _logger.info("Switched %d user(s) to %s.", len(users), CAMPUS_LANG)

    # The default for accounts created from here on.
    env['ir.default'].sudo().set('res.partner', 'lang', CAMPUS_LANG)

    # Load this module's own catalogue. Odoo imports i18n/<lang>.po for the
    # languages that are ACTIVE when a module's data is read, and id_ID was not
    # active a moment ago - this hook is what just turned it on. Modules
    # installed after campus_core pick their translations up by themselves;
    # campus_core is the one that would otherwise be left in English, taking
    # the menus, the field labels and the three report names with it.
    env['ir.module.module'].sudo().search([
        ('name', '=', 'campus_core'),
        ('state', 'in', ('installed', 'to install', 'to upgrade')),
    ])._update_translations(filter_lang=CAMPUS_LANG)


def post_init_hook(env):
    _set_campus_language(env)
