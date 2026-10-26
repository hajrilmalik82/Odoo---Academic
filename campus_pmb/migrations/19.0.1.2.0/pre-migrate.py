"""Check what the new constraints of this release would refuse.

Two things land here that an existing database may already violate:

* ``campus.admission.requirement`` carries a unique index on
  (document_type, admission_path, company_id).
* ``campus.admission`` now enforces its state graph on every write, so a row
  left in a state the graph cannot produce would be stuck.

Odoo only logs a warning when an index cannot be created
(odoo/orm/registry.py, finalize_constraints), so without this an upgrade over
bad data looks clean and the constraint silently does not exist. Nothing is
deleted or rewritten: what to do about a clash is a registrar's decision.
"""

import logging

_logger = logging.getLogger(__name__)

_KNOWN_STATES = ('draft', 'submitted', 'document_review', 'accepted', 'registered', 'rejected')


def migrate(cr, version):
    cr.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'campus_admission'")
    if not cr.fetchone():
        return

    # 1. Admissions sitting in a state the graph does not know.
    cr.execute(
        "SELECT state, count(*) FROM campus_admission WHERE state NOT IN %s GROUP BY state",
        (_KNOWN_STATES,),
    )
    for state, count in cr.fetchall():
        _logger.warning(
            "%s admission(s) are in state %r, which the state graph does not know. "
            "They can no longer be moved; set them to a known state first.",
            count, state,
        )

    # 2. Registered admissions with no student behind them - the exact damage
    #    the write guard now prevents.
    cr.execute(
        """
        SELECT count(*) FROM campus_admission
         WHERE state = 'registered' AND (partner_id IS NULL OR user_id IS NULL)
        """
    )
    (orphans,) = cr.fetchone()
    if orphans:
        _logger.warning(
            "%s admission(s) read Registered but have no student contact or no portal "
            "user. They were created before the state graph was enforced; run "
            "Register again on each one, or correct them by hand.",
            orphans,
        )
