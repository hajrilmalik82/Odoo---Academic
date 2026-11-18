# Campus Academic — SIAKAD for Odoo 19

Six single-company modules that together run an Indonesian campus: admissions,
employees, academic records, thesis & graduation management, the student portal,
and the public site. `campus_core` is the application; the rest are parts of
it, not separate apps.

## Install order

They declare their own dependencies, so installing `campus_portal`,
`campus_pmb`, and `campus_thesis` pulls everything else in. By hand, the order
is:

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
   students' records and student contacts a staff member reaches.
4. **campus_pmb** — new-student admission (PMB): the public application REST
   API, the document checklist, fees, the admission state machine, NIM
   generation and the student's portal account. Adds the PMB Staff role and
   the `pmb` jurisdiction scope.
5. **campus_portal** — `/my/krs` and `/my/khs` for students: select sections
   (including from pre-generated Semester 1–3 course packages) or add/retake
   courses, submit study plans, and print the KRS, KHS and transcript.
6. **campus_thesis** — end-to-end thesis (Skripsi) and Yudisium lifecycle:
   Research Methodology prerequisite, program-locked Primary Supervisor and
   optional Co-Supervisor, guidance progress logs, Thesis KRS enrollment gate,
   3-step Yudisium approvals (Supervisor → Academic Advisor → Dean), and quota-locked
   Graduation batch assignment.

## Tests

```
./jalankan-test.sh -d <db>
```

Over 280 tests across `TransactionCase` (model-level logic, ACLs, record rules,
state machines, concurrency locks) and `HttpCase` (routes, CSRF, QWeb
rendering, PDF generation, REST API, and language handling).

## Seeding a database to show

```
odoo-bin -c odoo.conf -d <db> -i campus_portal,campus_pmb,campus_thesis,campus_website --with-demo --stop-after-init
```

Two flags are easy to forget, and both have cost time here:

- **`--with-demo`.** Odoo 19 installs demo data only when asked. Without it the
  database comes up correct and completely empty.
- **`--i18n-overwrite`** when re-running an upgrade. Odoo does *not* replace a
  translation that already exists in the database, so editing an `id.po` and
  upgrading changes nothing — the old wording stays, including on printed
  transcripts. `jalankan-test.sh` passes it.

And one setting outside this repository: `odoo.conf` carries a `dbfilter`. A
database whose name does not match it is not served over HTTP at all, so the
site comes up blank with no error.

The demo data is a campus that works: two faculties, five programmes, a
curriculum with a real prerequisite chain, two terms, thirteen students, every
workflow state occupied. It is built through `action_submit`, so it refuses to
load if the credit cap, the prerequisites, the seat quota or the timetable
clash check breaks — it doubles as a smoke test. They are the reason several of the fixes in this history are safe to
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
- **Jurisdiction fields (`campus.jurisdiction`) are the access-control map.**
  Staff and PMB officers' faculty/programme assignments live on
  `campus.jurisdiction` (restricted to campus administrators) and are enforced
  by record rules on KRS, KHS, Thesis, Admission, and Student `res.partner`
  records. Writing a jurisdiction clears the registry cache because
  `ir.rule._compute_domain` is ormcached per user.
- **State machines are enforced on `write()`, not only on buttons.** Both
  `academic.krs` and `campus.admission` carry a `_STATE_TRANSITIONS` map, so a
  list-view inline edit, an import or a server action is validated the same way
  the buttons are.
- **The NIM prefix comes from `academic.faculty.code` and
  `academic.program.code`,** not from their names. A code is locked once a
  student number has been issued from it.
- **A unit is headed by one of its own.** `academic.faculty.dean_id` and
  `academic.program.head_id` accept only a lecturer of that faculty or that
  programme. Teaching is looser on purpose - `lecturer_id` on a schedule or a
  session accepts a lecturer of the programme *or* of its faculty, because
  teaching across programmes inside your own faculty is ordinary while heading
  somebody else's programme is not.

  All of it lives in `campus_employees`, not beside the fields it narrows:
  `academic_role`, `faculty_id` and `program_id` on `hr.employee` are its
  fields, and `campus_core` carries no dependency on it. The lecturer domain is
  declared once in `models/academic_teaching.py` and shared by the schedule and
  the session; a dynamic domain is evaluated by the CLIENT, so every view that
  picks a lecturer must also carry `class_program_id` and `class_faculty_id`,
  invisible. Leaving them out raises nothing - the domain quietly stops
  narrowing - so a test asserts their presence.

- **An academic advisor belongs to the student's own programme.**
  `res.partner.academic_advisor_id` offers only lecturers of that programme,
  and a constraint watches the student's `program_id` as well as the advisor
  field: moving a student to another programme is the quiet half of the rule,
  since the advisor field is never touched and a constraint on it alone would
  not fire. The narrowing used to be two `<field position="attributes">`
  overrides in views; on the field it holds in every view, and in an import.

- **Nobody moves while they are still wired up.** Changing an employee's
  faculty, programme or academic role is refused while anything still points at
  them - a deanship, a programme head post, a weekly schedule, a session, a
  student being advised - and the refusal lists all of them at once rather than
  one per attempt.

  The guard sits in `write()`, not in an `@api.constrains`. A constraint cannot
  see what a field held before the write, so it could not tell a move from a
  re-save that stores the value already there, and it fires after the fact when
  the point is to stop the change. Filling a profile in for the first time is
  not a move: `campus_core` builds the teaching schedule and `campus_employees`
  only afterwards says which faculty those lecturers belong to, so an
  empty-to-set write has to stay legal or the demo data refuses itself.
- **Single-company design.** The campus suite models a single institution
  (`env.company`) without per-record `company_id` multi-company overhead.

## Deliberate decisions that are not defects

- The demo-credentials panel on the login page and the email-derived portal
  passwords in `campus_pmb` are portfolio choices, not oversights.
- The developer contact details in the website footer are intentional.
- **`web_responsive/` is third-party and deliberate.** It is the OCA module of
  that name (LasLabs, Tecnativa and others, LGPL-3), vendored here rather than
  written for this project. No campus module depends on it and it is installed
  or not as the operator prefers; nothing in this suite assumes it.
- **Language.** English is the source and the default; Indonesian is a
  translation. Every user-facing string is written in English in the code and
  translated in `i18n/id.po`. `post_init_hook` activates `id_ID` and loads the
  catalogue, and `campus_website` adds it to each site's languages, so the
  option is there for anyone who wants it - but nothing switches a user or a
  site to it. A reader who wants Indonesian chooses it in Preferences.

  New strings follow the same rule - English in `_()`, Indonesian in the
  catalogue - never Indonesian in the source, because an Indonesian msgid
  cannot be translated and renders by falling back to itself. The one label
  outside the catalogue is the website main menu, which is record data rather
  than a catalogue term: `campus_website` writes both keys by hand in
  `data/website_configurator_bypass.xml`.

  This is the second arrangement. The first one wrote `lang` on every user and
  set a default on `res.partner`, which switched an administrator working in
  English to Indonesian on install, with no setting to point at.
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
