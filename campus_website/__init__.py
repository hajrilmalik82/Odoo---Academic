import logging

_logger = logging.getLogger(__name__)

CAMPUS_LANG = 'id_ID'

MAIN_MENU_LABEL = 'Guide'
MAIN_MENU_LABEL_ID = 'Panduan'


def _offer_indonesian(env):
    """Add Indonesian to every site without making it the default.

    A frontend page renders in the WEBSITE's language, not the visitor's, and a
    language missing from website.language_ids cannot be reached from the
    frontend at all - the switcher does not list it and /id_ID/... is a 404. So
    the language has to be added to each site even though English remains the
    default, exactly as it is in the backend.

    Returns the language, or an empty recordset if it could not be activated.
    """
    lang = env['res.lang']._activate_lang(CAMPUS_LANG)
    if not lang:
        _logger.warning("Could not activate %s; the site stays English-only.", CAMPUS_LANG)
        return lang

    websites = env['website'].sudo().search([])
    if websites:
        # (4, id) ADDS. This was a (6, 0, ids), which REPLACES: it threw en_US
        # out of every site and pinned default_lang_id to Indonesian, so a
        # visitor had no way back to the language the source is written in.
        websites.write({'language_ids': [(4, lang.id)]})
        _logger.info("Added %s to %d website(s).", CAMPUS_LANG, len(websites))
    return lang


def _label_main_menu(env, with_indonesian):
    """Rename the menu at '/' from Odoo's "Home" to this suite's own label.

    Searched by url, NOT by ref('website.menu_home'). That xmlid is the
    TEMPLATE menu, carrying website_id = False; every website gets its own copy
    of the tree when it is created, and the copy is what the header actually
    renders. Writing to the template alone renamed a menu nobody sees - which
    went unnoticed while a line of JavaScript renamed the visible one on the
    client.

    Done here rather than in data/website_configurator_bypass.xml for two
    reasons. A <record> override of website.menu_home would clear the noupdate
    flag that stops `-u website` restoring the stock "Home"
    (addons/website/data/website_data.xml:508); a plain write leaves website's
    own protection intact. And the Indonesian key has to be written per record,
    because update_field_translations is ensure_one() and there is always more
    than one menu at '/' - a <function> cannot loop, which is exactly how the
    first attempt at this broke every fresh install.

    website.menu.name is record data rather than a catalogue term, so i18n
    export never sees it and no .po entry can carry the translation.
    """
    menus = env['website.menu'].sudo().search([('url', '=', '/')])
    if not menus:
        return
    menus.write({'name': MAIN_MENU_LABEL})
    if with_indonesian:
        for menu in menus:
            menu.update_field_translations('name', {CAMPUS_LANG: MAIN_MENU_LABEL_ID})
    _logger.info("Labelled %d main menu(s) as %s.", len(menus), MAIN_MENU_LABEL)


def post_init_hook(env):
    """Install-time only. An administrator who later drops Indonesian, makes it
    the site default, or renames the menu is making a deliberate choice, and
    nothing here must undo it on the next upgrade."""
    lang = _offer_indonesian(env)
    _label_main_menu(env, with_indonesian=bool(lang))
