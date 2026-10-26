import logging

_logger = logging.getLogger(__name__)

CAMPUS_LANG = 'id_ID'


def post_init_hook(env):
    """Serve the site in Indonesian.

    A frontend page renders in the WEBSITE's language, not the visitor's, so a
    website left on en_US showed English to a signed-in Indonesian student
    whatever their own language setting said. campus_core makes id_ID the
    language of the system and of the users; this makes it the language of the
    sites.

    Install-time only: an administrator who later adds English back, or
    switches the site to another language, is making a deliberate choice.
    """
    lang = env['res.lang']._activate_lang(CAMPUS_LANG)
    if not lang:
        _logger.warning("Could not activate %s; the site stays in English.", CAMPUS_LANG)
        return
    websites = env['website'].sudo().search([])
    if websites:
        websites.write({
            'language_ids': [(6, 0, lang.ids)],
            'default_lang_id': lang.id,
        })
        _logger.info("Set %s as the language of %d website(s).", CAMPUS_LANG, len(websites))
