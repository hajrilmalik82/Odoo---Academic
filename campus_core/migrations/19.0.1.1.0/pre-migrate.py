"""Replace the two band UNIQUE constraints with COALESCE unique indexes.

academic.credit.limit and academic.grade.scale used to declare
`models.Constraint('UNIQUE (min_cgpa, company_id)')`. PostgreSQL treats NULLs
as distinct, and every band the module ships has company_id unset, so the
constraint never fired on the data it was written to protect. The models now
declare `models.UniqueIndex("(min_cgpa, COALESCE(company_id, 0))")` instead.

Odoo will not create an index whose name is already taken, and a UNIQUE table
constraint owns an index of its own name, so without this the rename is a
silent no-op: the upgrade logs nothing and the old, inert definition stays.
Dropping the constraint here, before the models are loaded, leaves the name
free for the real index.

Duplicate rows are reported rather than deleted - which band a campus keeps is
a registrar's decision, not a migration's.
"""

import logging

_logger = logging.getLogger(__name__)

_BANDS = (
    ('academic_credit_limit', 'academic_credit_limit_unique_band_per_company', 'min_cgpa'),
    ('academic_grade_scale', 'academic_grade_scale_unique_score_per_company', 'min_score'),
)


def migrate(cr, version):
    for table, name, column in _BANDS:
        cr.execute("SELECT 1 FROM information_schema.tables WHERE table_name = %s", (table,))
        if not cr.fetchone():
            continue

        cr.execute(
            """
            SELECT %(column)s, count(*)
              FROM %(table)s
             WHERE company_id IS NULL
          GROUP BY %(column)s
            HAVING count(*) > 1
            """.replace('%(column)s', column).replace('%(table)s', table)
        )
        duplicates = cr.fetchall()
        if duplicates:
            _logger.warning(
                "%s: duplicate bands at %s - the new unique index cannot be created "
                "until one of each pair is removed in Configuration.",
                table, ', '.join(str(value) for value, _count in duplicates),
            )
            continue

        cr.execute(
            "SELECT 1 FROM pg_constraint WHERE conname = %s AND conrelid = %s::regclass",
            (name, table),
        )
        if cr.fetchone():
            cr.execute('ALTER TABLE "%s" DROP CONSTRAINT "%s"' % (table, name))
            _logger.info("%s: dropped UNIQUE constraint %s, replaced by a COALESCE index", table, name)
