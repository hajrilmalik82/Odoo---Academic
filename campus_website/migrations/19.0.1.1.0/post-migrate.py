"""Carry the main-menu rename to databases that already exist.

data/website_configurator_bypass.xml renames the menu at '/' to "Panduan", and
it is noupdate="1" - it sets the site up once, on install, and never fires
again. That is deliberate: the alternative is a data file that overwrites the
administrator's own choices on every upgrade, which this suite has already been
bitten by once.

The consequence is that fixing the rename fixed it only for new installs. The
rename used to target ref('website.menu_home'), which is the TEMPLATE menu
carrying website_id = False; every website holds its own copy of the tree and
that copy is what the header renders, so the visible menu was never touched.

This is the deliberate act that reaches the databases the data file cannot.
Only menus still called "Home" are renamed: a site owner who has already chosen
their own label has made a decision, and an upgrade must not overrule it.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'website_menu'")
    if not cr.fetchone():
        return

    # website_menu.name is a translated field, stored as jsonb. The whole value
    # is replaced rather than just the en_US key: Odoo's own website catalogue
    # translates "Home" to "Beranda", and a stale id_ID key would keep showing
    # that on an Indonesian site however the source string is renamed. With
    # only en_US present, every language falls back to it.
    cr.execute(
        """
        UPDATE website_menu
           SET name = '{"en_US": "Panduan"}'::jsonb
         WHERE url = '/'
           AND name->>'en_US' = 'Home'
        RETURNING id
        """
    )
    renamed = cr.fetchall()
    if renamed:
        _logger.info("Renamed %s main menu(s) from Home to Panduan.", len(renamed))
    else:
        _logger.info("No main menu left to rename; nothing to do.")
