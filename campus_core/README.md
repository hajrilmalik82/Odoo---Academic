# Campus Academic — SIAKAD for Odoo 19

Five modules that together run an Indonesian campus: admissions, employees,
academic records, the student portal and the public site. `campus_core` is the
application; the rest are parts of it, not separate apps.

## Install order

They declare their own dependencies, so installing `campus_portal` and
`campus_pmb` pulls everything else in. By hand, the order is:

1. **campus_core** — faculties, study programmes, subjects, academic years,
   classes and schedules, KRS (study plan), KHS (term grades), the transcript,
   the grade scale and the credit-limit bands. Owns the three PDF reports and
   the campus access groups. Deliberately does **not** depend on `website`: a
   core module carries the domain and must install on a database that has no
   website at all.
2. **campus_website** — everything the suite puts on the public site: the
   header and footer chrome, the demo login panel, the documentation page at
   `/`, and the one-off setup that skips Odoo's website configurator.
3. **campus_employees** — the academic roles on `hr.employee` (Lecturer,
   Academic Staff) and `campus.jurisdiction`, the model that decides which
   students' records a staff member reaches.
4. **campus_pmb** — new-student admission (PMB): the public application form,
   the document checklist, the admission state machine, NIM generation and the
   student's portal account. Adds the PMB Staff role and the `pmb` jurisdiction
   scope.
5. **campus_portal** — `/my/krs` and `/my/khs` for students: fill in a study
   plan, submit it, print the KRS, KHS and transcript.

## Tests

```
odoo-bin -c odoo.conf -d <db> -u campus_core,campus_website,campus_employees,campus_pmb,campus_portal --test-enable --stop-after-init
```

96 tests. They are the reason several of the fixes in this history are safe to
make: the suite found two real defects while it was being restored — a
`check_company` that made every student contact impossible to save, and a
`NULLS FIRST` ordering that picked the wrong grade band.

The fixtures prefix every record they create with `ZZTEST` and roll back at the
end, so they run against a working database without colliding with its master
data. Do not remove that prefix: several models enforce uniqueness on name or
code, and plausible-looking test names collided with real ones.

## Things worth knowing before changing anything

- **Access control is layered.** ACL rows in `security/ir.model.access.csv` say
  which models a group may touch; `ir.rule` records in `security/*.xml` say
  which *rows*. Several rules exist only to re-widen a restriction for
  administrators, because `group_campus_administrator` implies the lecturer and
  academic-staff groups and rules of different groups are OR'ed.
- **Jurisdiction fields are the access-control map.** The four `academic_*` and
  four `pmb_*` fields on `hr.employee` are what the record rules read. They are
  restricted to campus administrators and writing them clears the registry
  cache, because `ir.rule._compute_domain` is ormcached per user and the
  jurisdiction is not part of that cache key.
- **State machines are enforced on `write()`, not only on buttons.** Both
  `academic.krs` and `campus.admission` carry a `_STATE_TRANSITIONS` map, so a
  list-view inline edit, an import or a server action is validated the same way
  the buttons are.
- **The NIM prefix comes from `academic.faculty.code` and
  `academic.program.code`,** not from their names. A code is locked once a
  student number has been issued from it.
- **Migrations live in `campus_core/migrations/<version>/`.** Bump the module
  version in the manifest on any release that changes schema, data or views, and
  bump all four together for a change that crosses modules.

## Deliberate decisions that are not defects

- The demo-credentials panel on the login page and the email-derived portal
  passwords in `campus_pmb` are portfolio choices, not oversights.
- The developer contact details in the website footer are intentional.
- **Language.** Source strings are English, the interface is Indonesian. Every
  user-facing string is written in English in the code and translated in
  `i18n/id.po`; `post_init_hook` activates `id_ID` and makes it the language of
  the websites and the users. New strings follow the same rule - English in
  `_()`, Indonesian in the catalogue - never Indonesian in the source, because
  an Indonesian msgid cannot be translated and renders by falling back to itself.
- **The documentation page is translated where it was already translated.** The
  four `website_homepage_*.xml` templates are technical documentation for a
  reviewer rather than an operational screen, so the parts still in English are
  left that way rather than translated for the sake of it. They are counted
  separately from the operational catalogue so the untranslated figure stays
  meaningful.
- **Jurisdiction is one model, not eight fields.** `campus.jurisdiction` holds
  one row per (employee, scope); `campus_employees` owns it and `campus_pmb`
  adds its scope with `selection_add`. It is the access-control map, so its ACL
  admits campus administrators only — read included — and everything that
  consumes it goes through `_jurisdiction_domain`, which sudoes.
- **Migrations live in `<module>/migrations/<version>/`** and several of them
  only report. Odoo logs a warning and carries on when an index cannot be
  created, so an upgrade over data that violates a new constraint looks clean
  while the constraint silently does not exist. Those scripts say so out loud.
