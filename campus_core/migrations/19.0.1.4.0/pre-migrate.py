"""Re-home the website records from campus_core to campus_website.

The templates, the login panel and the configurator bypass moved module. Their
ir.model.data rows still say campus_core, and on the next upgrade Odoo deletes
the records of xmlids a module no longer provides - so without this the views
would be dropped and recreated under the new module.

That matters for more than tidiness. A view edited through the website editor
is stored as a copy keyed to the original, and deleting the original leaves
that copy pointing at nothing. Updating the owner instead keeps every record,
every id and every customisation exactly where it is.

This lives in campus_core, not in campus_website, and that is not arbitrary:
Odoo runs migration scripts when a module is UPGRADED, never when one is first
installed. campus_website is new to every database that needs this, so a script
of its own would never execute. campus_core is the module being upgraded, it
owns the rows today, and it is loaded first - so by the time campus_website's
data file is read, the xmlids already point at it.
"""

import logging

_logger = logging.getLogger(__name__)

_MOVED = (
    # (model, xmlid name)
    ('ir.ui.view', 'core_homepage_docs'),
    ('ir.ui.view', 'campus_website_layout'),
    ('ir.ui.view', 'campus_website_layout_footer'),
    ('ir.ui.view', 'campus_demo_login'),
)


def migrate(cr, version):
    cr.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'ir_model_data'")
    if not cr.fetchone():
        return

    names = tuple(name for _model, name in _MOVED)
    cr.execute(
        """
        UPDATE ir_model_data
           SET module = 'campus_website'
         WHERE module = 'campus_core'
           AND name IN %s
        RETURNING name
        """,
        (names,),
    )
    moved = [row[0] for row in cr.fetchall()]
    if moved:
        _logger.info("Re-homed %s to campus_website: %s", len(moved), ', '.join(moved))

    missing = set(names) - set(moved)
    if missing:
        # Either already re-homed by an earlier run, or never installed. Both
        # are fine; say so rather than leaving it to be guessed.
        _logger.info("Nothing to re-home for: %s", ', '.join(sorted(missing)))
