"""Report duplicate faculty/programme codes before the unique index is built.

academic.faculty.code and academic.program.code now carry a unique index: the
NIM prefix is built from them, so two records sharing a code issue student
numbers that cannot be told apart.

The codes were seeded in 19.0.1.2.0 from the initials of each name, and that
derivation collides on the pair every Indonesian campus has - "Teknik
Informatika" and "Teknik Industri" both reduce to TI. Odoo only logs a warning
when an index cannot be created (odoo/orm/registry.py finalize_constraints), so
without this the upgrade would look clean and the constraint would silently not
exist.

Nothing is renamed here. Which programme keeps which code is a registrar's
decision - the convention on Indonesian campuses is Informatika = IF, Industri
= TI - so this reports the clash and names the records to fix.
"""

import logging

_logger = logging.getLogger(__name__)

_TABLES = (
    ('academic_faculty', 'Faculty'),
    ('academic_program', 'Programme'),
)


def migrate(cr, version):
    for table, label in _TABLES:
        cr.execute("SELECT 1 FROM information_schema.tables WHERE table_name = %s", (table,))
        if not cr.fetchone():
            continue
        cr.execute(
            """
            SELECT upper(code), array_agg(name ORDER BY id)
              FROM {table}
             WHERE code IS NOT NULL AND code <> ''
          GROUP BY upper(code), COALESCE(company_id, 0)
            HAVING count(*) > 1
            """.format(table=table)
        )
        for code, names in cr.fetchall():
            _logger.warning(
                "%s code '%s' is shared by %s. Student numbers built from it cannot "
                "be told apart; give each one a distinct code in "
                "Academic System > Configuration.",
                label, code, ', '.join(names),
            )
