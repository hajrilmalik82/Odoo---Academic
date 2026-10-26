from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


# Marker for the guard on hr.department: writes coming from THIS file are the
# sync itself and must be allowed through. See campus_core/models/hr_department.py.
_SYNC = {'campus_mirror_sync': True}


def _drop_linked_departments(departments):
    """Remove the HR departments that mirrored the deleted academic records.

    Must run after super().unlink(): department_id is ondelete='restrict', so
    the department can only go once the row pointing at it is gone.

    Deleting a faculty or a programme used to leave its department behind, and
    the HR Departments list slowly filled with entries for faculties and
    programmes that no longer existed, several of them sharing a name.

    Refuses while people are still assigned. hr.version.department_id is
    ON DELETE SET NULL, so removing an occupied department would quietly strip
    the department from every employee in it and leave nothing behind to say
    what it used to be.
    """
    if not departments:
        return
    occupied = departments.filtered('member_ids')
    if occupied:
        raise UserError(_(
            "Cannot delete %(names)s: employees are still assigned to the "
            "linked HR department. Move them to another department first."
        ) % {
            'names': ', '.join(occupied.mapped('name')),
        })
    departments.with_context(campus_mirror_sync=True).unlink()


def _derive_code(name):
    """Initials of a name, as the NIM generator used to compute them inline.

    Only ever used to seed `code` when a record is created without one, so the
    first NIM a new faculty or programme issues looks like the ones before it.
    After that the stored code is what counts, and renaming the record no
    longer touches it.
    """
    initials = "".join(word[0].upper() for word in (name or '').split() if word.isalpha())
    return initials[:2] or 'XX'


class AcademicFaculty(models.Model):
    _name = 'academic.faculty'
    _description = 'Academic Faculty'
    _order = 'name'
    _check_company_auto = True

    # Case-insensitive on purpose: a plain UNIQUE (name) compares byte for byte,
    # so "Fakultas Teknologi Industri" and "FAKULTAS TEKNOLOGI INDUSTRI" were
    # accepted as two different faculties and then sat side by side in the HR
    # department tree with no way to tell them apart. An index on lower(name) is
    # what makes the two collide.
    # Immutable short code, and the half of a NIM that must never move. NIMs
    # used to be built from the first letters of the CURRENT display name, so
    # renaming "Fakultas Teknik" to "Fakultas Teknologi Industri" silently
    # changed the prefix for every student admitted afterwards, splitting one
    # faculty's cohort across two numbering series. Derived from the name only
    # at creation, as a starting point; after that it is the registrar's to set
    # and the constraint below stops it moving once NIMs exist.
    code = fields.Char(
        string='Code', size=4, copy=False,
        help="Short code used to build student numbers (NIM). Cannot be changed "
             "once a student number has been issued from it.",
    )

    # The NIM prefix is built from this, so two records sharing a code produce
    # student numbers that cannot be told apart. The automatic derivation
    # collides on exactly the pair a real campus has - "Teknik Informatika" and
    # "Teknik Industri" both reduce to TI - so the database has to refuse it
    # rather than leave it to be noticed years later. COALESCE for the same
    # reason as everywhere else here: NULLs are distinct in PostgreSQL.
    _unique_code_per_company = models.UniqueIndex(
        "(upper(code), COALESCE(company_id, 0)) WHERE code IS NOT NULL",
        "Faculty code must be unique: it is what student numbers are built from.",
    )

    # Kept global, not scoped by company_id, and deliberately so: this suite
    # models one institution, every ir.rule in it is written without a company
    # clause, and two faculties with the same name in one database would be a
    # data-entry mistake whichever company they belong to. Scoping the index by
    # company only becomes right once there are company record rules to go with
    # it; until then it would quietly allow the duplicates this index exists to
    # catch. (This used to defer to "audit item S-07", a document that is not in
    # this repository and never was.)
    _unique_name_case_insensitive = models.UniqueIndex(
        "(lower(name))",
        "Faculty name must be unique!",
    )

    name = fields.Char(string='Name', required=True)
    dean_id = fields.Many2one('hr.employee', string="Head of Faculty / Dean", check_company=True)
    department_id = fields.Many2one('hr.department', string="Linked HR Department", ondelete='restrict', copy=False)
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company
    )


    def _issued_nim_count(self):
        """How many student numbers already carry this record's code."""
        self.ensure_one()
        return self.env['res.partner'].sudo().search_count([
            ('nim', '!=', False),
            ('program_id.faculty_id', '=', self.id),
        ])

    @api.constrains('code')
    def _check_code_not_reused(self):
        """A code may be corrected right up until it has issued a NIM.

        After that it is baked into student numbers printed on transcripts,
        cards and every KHS already issued, so changing it would leave those
        documents carrying a prefix the system no longer produces.
        """
        for record in self:
            if record._issued_nim_count():
                raise ValidationError(_(
                    "The code of '%(name)s' can no longer be changed: student "
                    "numbers have already been issued from it."
                ) % {'name': record.display_name})

    @api.model_create_multi
    def create(self, vals_list):
        # Checked up front: the loop below creates an hr.department before
        # super() gets to verify the caller may create a faculty at all. Without
        # this, a user without create rights was refused by a message naming
        # hr.department, which says nothing about what they actually lack.
        self.check_access('create')
        for vals in vals_list:
            if not vals.get('code'):
                vals['code'] = _derive_code(vals.get('name'))
        # One hr.department.create for the whole batch rather than one per
        # faculty: seeding master data used to cost a round trip per row.
        needing = [vals for vals in vals_list if 'name' in vals and not vals.get('department_id')]
        if needing:
            departments = self.env['hr.department'].create([{
                'name': vals['name'],
                'manager_id': vals.get('dean_id', False),
            } for vals in needing])
            for vals, department in zip(needing, departments):
                vals['department_id'] = department.id
        return super().create(vals_list)

    def write(self, vals):
        # Captured before the write, so the programme heads below can tell
        # whether they were reporting to the dean who is now leaving.
        outgoing_deans = {faculty.id: faculty.dean_id for faculty in self} if 'dean_id' in vals else {}
        res = super().write(vals)
        # One search for the whole batch. This used to run inside the loop, so a
        # bulk dean rotation cost one academic.program search per faculty on top
        # of the per-programme writes.
        programs_by_faculty = {}
        if 'dean_id' in vals:
            for program in self.env['academic.program'].search([('faculty_id', 'in', self.ids)]):
                programs_by_faculty.setdefault(program.faculty_id.id, []).append(program)
        for faculty in self:
            if not faculty.department_id:
                continue
            if 'name' in vals:
                faculty.department_id.with_context(campus_mirror_sync=True).name = faculty.name
            if 'dean_id' in vals:
                # Written even when the Dean is cleared. hr.department answers a
                # manager change by re-parenting the employees of that department
                # whose manager was the outgoing dean, and only those: a colleague
                # who reports to somebody else keeps their manager. An earlier fix
                # here refused to write a blank manager, on the belief that it wiped
                # the manager of everyone in the faculty. It does not, and the
                # refusal left the department showing a dean the faculty no longer
                # had, with the faculty's staff still reporting to them.
                faculty.department_id.with_context(campus_mirror_sync=True).manager_id = faculty.dean_id.id
                for program in programs_by_faculty.get(faculty.id, ()):
                    program._set_head_reports_to(faculty.dean_id, outgoing_deans.get(faculty.id))
        return res

    def unlink(self):
        departments = self.department_id
        res = super().unlink()
        _drop_linked_departments(departments)
        return res


class AcademicProgram(models.Model):
    _name = 'academic.program'
    _description = 'Academic Program'
    _order = 'name'
    _check_company_auto = True

    # Global, not scoped by faculty. A programme name identifies the programme
    # across the whole institution: "Teknik Informatika" belongs to exactly one
    # faculty, and the same name appearing under two faculties is a data-entry
    # mistake rather than a legitimate second programme. Scoped by faculty, the
    # constraint accepted those duplicates, and they then showed up twice in the
    # HR department tree with no way to tell them apart.
    # Kept company-wide, and case-insensitive, for the same reasons as
    # academic.faculty above.
    # The NIM prefix is built from this, so two records sharing a code produce
    # student numbers that cannot be told apart. The automatic derivation
    # collides on exactly the pair a real campus has - "Teknik Informatika" and
    # "Teknik Industri" both reduce to TI - so the database has to refuse it
    # rather than leave it to be noticed years later. COALESCE for the same
    # reason as everywhere else here: NULLs are distinct in PostgreSQL.
    _unique_code_per_company = models.UniqueIndex(
        "(upper(code), COALESCE(company_id, 0)) WHERE code IS NOT NULL",
        "Programme code must be unique: it is what student numbers are built from.",
    )

    _unique_name_case_insensitive = models.UniqueIndex(
        "(lower(name))",
        "Program name must be unique!",
    )

    name = fields.Char(string='Name', required=True)
    # Immutable short code, and the half of a NIM that must never move. NIMs
    # used to be built from the first letters of the CURRENT display name, so
    # renaming "Fakultas Teknik" to "Fakultas Teknologi Industri" silently
    # changed the prefix for every student admitted afterwards, splitting one
    # programme's cohort across two numbering series. Derived from the name only
    # at creation, as a starting point; after that it is the registrar's to set
    # and the constraint below stops it moving once NIMs exist.
    code = fields.Char(
        string='Code', size=4, copy=False,
        help="Short code used to build student numbers (NIM). Cannot be changed "
             "once a student number has been issued from it.",
    )
    faculty_id = fields.Many2one(
        'academic.faculty', string='Faculty', required=True, check_company=True,
        # Searched by faculty on every programme list and by the jurisdiction
        # record rules in campus_employees.
        index=True,
    )
    head_id = fields.Many2one('hr.employee', string="Head of Program", check_company=True)
    department_id = fields.Many2one('hr.department', string="Linked HR Department", ondelete='restrict', copy=False)
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company
    )


    def _issued_nim_count(self):
        """How many student numbers already carry this record's code."""
        self.ensure_one()
        return self.env['res.partner'].sudo().search_count([
            ('nim', '!=', False),
            ('program_id', '=', self.id),
        ])

    @api.constrains('code')
    def _check_code_not_reused(self):
        """A code may be corrected right up until it has issued a NIM.

        After that it is baked into student numbers printed on transcripts,
        cards and every KHS already issued, so changing it would leave those
        documents carrying a prefix the system no longer produces.
        """
        for record in self:
            if record._issued_nim_count():
                raise ValidationError(_(
                    "The code of '%(name)s' can no longer be changed: student "
                    "numbers have already been issued from it."
                ) % {'name': record.display_name})

    @api.model_create_multi
    def create(self, vals_list):
        # Same reason as on the faculty above.
        self.check_access('create')
        for vals in vals_list:
            if not vals.get('code'):
                vals['code'] = _derive_code(vals.get('name'))
        for vals in vals_list:
            if 'name' in vals and not vals.get('department_id'):
                parent_dept_id = False
                if vals.get('faculty_id'):
                    faculty = self.env['academic.faculty'].browse(vals['faculty_id'])
                    parent_dept_id = faculty.department_id.id if faculty.department_id else False
                dept = self.env['hr.department'].create({
                    'name': vals['name'],
                    'parent_id': parent_dept_id,
                    'manager_id': vals.get('head_id', False)
                })
                vals['department_id'] = dept.id
        programs = super().create(vals_list)
        for program in programs:
            program._set_head_reports_to(program.faculty_id.dean_id)
        return programs

    def _set_head_reports_to(self, dean, outgoing_dean=None):
        """Point the programme head at the dean, unless they are the same person.

        hr.employee.parent_id carries no recursion guard in Odoo, so making
        someone their own manager goes through silently and leaves a self-loop in
        the org chart. That happens whenever a dean also heads one of their own
        faculty's programmes, which is ordinary at a small campus.

        The clearing branch exists because a programme head is usually not a
        member of the faculty's own HR department, so hr.department's re-parenting
        never reaches them. Without it, removing a dean left every head of that
        faculty still reporting to someone who no longer held the post. Only the
        link this method created is undone: a head who reports to somebody else
        keeps their manager.
        """
        self.ensure_one()
        if not self.head_id:
            return
        if dean:
            if self.head_id != dean:
                self.head_id.parent_id = dean.id
        elif outgoing_dean and self.head_id.parent_id == outgoing_dean:
            self.head_id.parent_id = False

    def write(self, vals):
        res = super().write(vals)
        for program in self:
            if not program.department_id:
                continue
            if 'name' in vals:
                program.department_id.with_context(campus_mirror_sync=True).name = program.name
            if 'head_id' in vals:
                # Same reasoning as the dean above: a cleared Head of Program
                # leaves the programme's department without a manager.
                program.department_id.with_context(campus_mirror_sync=True).manager_id = program.head_id.id
                if program.head_id:
                    program._set_head_reports_to(program.faculty_id.dean_id)
            if 'faculty_id' in vals:
                program.department_id.with_context(campus_mirror_sync=True).parent_id = (
                    program.faculty_id.department_id.id if program.faculty_id.department_id else False
                )
        return res

    def unlink(self):
        departments = self.department_id
        res = super().unlink()
        _drop_linked_departments(departments)
        return res
