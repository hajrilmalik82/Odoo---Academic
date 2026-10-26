"""Confirm the PMB jurisdiction relation tables survived the module move.

The four ``pmb_*`` jurisdiction fields moved from campus_employees to
campus_pmb. Their many2many relation table names are stated explicitly in the
field definitions precisely so the existing assignments travel with them - if a
table name ever drifts, Odoo creates a fresh empty one and every PMB officer
silently loses their faculties and programmes, which a record rule then reads
as "no jurisdiction at all".

That failure is invisible: no error, just an officer who can suddenly see
nothing. This is the cheapest possible check that it did not happen.
"""

import logging

_logger = logging.getLogger(__name__)

_RELATIONS = ('hr_employee_pmb_faculty_rel', 'hr_employee_pmb_program_rel')


def migrate(cr, version):
    for table in _RELATIONS:
        cr.execute("SELECT 1 FROM information_schema.tables WHERE table_name = %s", (table,))
        if not cr.fetchone():
            _logger.error(
                "Relation table %s is missing after the upgrade. PMB jurisdiction "
                "assignments have been lost and must be re-entered.", table,
            )
            continue
        cr.execute('SELECT count(*) FROM "%s"' % table)
        (rows,) = cr.fetchone()
        _logger.info("%s: %s jurisdiction assignment(s) carried over.", table, rows)
