"""Move the pmb_* jurisdiction onto campus.jurisdiction.

The four fields on hr.employee - pmb_all_faculties, pmb_faculty_ids,
pmb_all_programs, pmb_program_ids - became a row with scope 'pmb'. The columns and the two relation tables are still there at this
point (Odoo leaves dropped fields' storage alone), so the data is read straight
out of them.

Jurisdiction decides which applicants' records a staff member reaches. Losing it
silently would not raise anything: a record rule reads "no assignment" as "no
access", so an officer would simply find the system empty one morning. Hence
this runs in post-migrate, after the new table exists, and logs what it moved.
"""

import logging

_logger = logging.getLogger(__name__)

_OLD_COLUMNS = ('pmb_all_faculties', 'pmb_all_programs')
# The column in a many2many relation table is named after the COMODEL, not
# after the field, so both the academic and the PMB tables use
# academic_faculty_id / academic_program_id.
_OLD_RELATIONS = (
    ('hr_employee_pmb_faculty_rel', 'academic_faculty_id', 'campus_jurisdiction_faculty_rel', 'faculty_id'),
    ('hr_employee_pmb_program_rel', 'academic_program_id', 'campus_jurisdiction_program_rel', 'program_id'),
)


def _column_exists(cr, table, column):
    cr.execute(
        """SELECT 1 FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s""",
        (table, column),
    )
    return bool(cr.fetchone())


def _table_exists(cr, table):
    cr.execute("SELECT 1 FROM information_schema.tables WHERE table_name = %s", (table,))
    return bool(cr.fetchone())


def migrate(cr, version):
    if not _table_exists(cr, 'campus_jurisdiction'):
        _logger.error("campus_jurisdiction does not exist; jurisdiction was NOT migrated.")
        return

    have_columns = [c for c in _OLD_COLUMNS if _column_exists(cr, 'hr_employee', c)]
    sources = [r for r in _OLD_RELATIONS if _table_exists(cr, r[0])]
    if not have_columns and not sources:
        _logger.info("No legacy academic jurisdiction found; nothing to migrate.")
        return

    # Every employee that had anything set at all.
    employee_ids = set()
    for column in have_columns:
        cr.execute('SELECT id FROM hr_employee WHERE "%s" IS TRUE' % column)
        employee_ids.update(row[0] for row in cr.fetchall())
    for table, _col, _dest, _destcol in sources:
        cr.execute('SELECT DISTINCT hr_employee_id FROM "%s"' % table)
        employee_ids.update(row[0] for row in cr.fetchall())
    if not employee_ids:
        _logger.info("No employee carried an academic jurisdiction; nothing to migrate.")
        return

    created = 0
    for employee_id in sorted(employee_ids):
        all_faculties = all_programs = False
        for column in have_columns:
            cr.execute('SELECT "%s" FROM hr_employee WHERE id = %%s' % column, (employee_id,))
            value = (cr.fetchone() or [None])[0]
            if column.endswith('_faculties'):
                all_faculties = bool(value)
            else:
                all_programs = bool(value)

        cr.execute(
            """
            INSERT INTO campus_jurisdiction
                   (employee_id, scope, all_faculties, all_programs)
            VALUES (%s, 'pmb', %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (employee_id, all_faculties, all_programs),
        )
        row = cr.fetchone()
        if not row:
            continue
        jurisdiction_id = row[0]
        created += 1

        for table, source_col, dest_table, dest_col in sources:
            cr.execute(
                'SELECT "%s" FROM "%s" WHERE hr_employee_id = %%s' % (source_col, table),
                (employee_id,),
            )
            for (target_id,) in cr.fetchall():
                cr.execute(
                    'INSERT INTO "%s" (jurisdiction_id, "%s") VALUES (%%s, %%s) '
                    'ON CONFLICT DO NOTHING' % (dest_table, dest_col),
                    (jurisdiction_id, target_id),
                )

    _logger.info("Migrated academic jurisdiction for %s employee(s).", created)
