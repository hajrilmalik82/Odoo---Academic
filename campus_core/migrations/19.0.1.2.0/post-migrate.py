"""Backfill academic.faculty.code and academic.program.code.

NIM prefixes used to be derived from the first letters of the faculty's and
programme's current display names, so a rename silently changed the numbering
for every student admitted afterwards. The prefix now comes from a stored
`code` instead.

Existing rows are seeded with exactly the value the old derivation produced, so
the next NIM issued after this upgrade continues the series already in use
rather than starting a new one. Rows that already carry a code are left alone.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo.addons.campus_core.models.academic_institution import _derive_code

    for table in ('academic_faculty', 'academic_program'):
        cr.execute(
            'SELECT id, name FROM "%s" WHERE code IS NULL OR code = \'\'' % table
        )
        rows = cr.fetchall()
        for record_id, name in rows:
            cr.execute(
                'UPDATE "%s" SET code = %%s WHERE id = %%s' % table,
                (_derive_code(name), record_id),
            )
        if rows:
            _logger.info("%s: seeded code for %d row(s) from their current names", table, len(rows))
