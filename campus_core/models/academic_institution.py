from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


def _normalize_code(code):
    """Trim surrounding whitespace and uppercase an explicit institution code."""
    cleaned = (code or '').strip().upper()
    return cleaned or False


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
    occupied = departments.with_context(active_test=False).filtered(
        lambda dept: dept.env['hr.employee'].sudo().with_context(active_test=False).search_count([
            ('department_id', '=', dept.id),
        ])
    )
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
    _rec_names_search = ['name', 'code']

    # Immutable short code used as part of the student number (NIM) prefix.
    # Derived from the name only at creation when omitted; locked once NIMs exist.
    code = fields.Char(
        string='Code', size=4, copy=False,
        help="Short code used to build student numbers (NIM). Cannot be changed "
             "once a student number has been issued from it.",
    )

    _unique_code = models.UniqueIndex(
        "(upper(code)) WHERE code IS NOT NULL",
        "Faculty code must be unique: it is what student numbers are built from.",
    )

    # Case-insensitive: prevents near-duplicate faculty names side by side in
    # the HR department tree.
    _unique_name_case_insensitive = models.UniqueIndex(
        "(lower(name))",
        "Faculty name must be unique!",
    )

    _unique_department = models.UniqueIndex(
        "(department_id) WHERE department_id IS NOT NULL",
        "Each HR department can only mirror one academic faculty.",
    )

    name = fields.Char(string='Name', required=True)
    dean_id = fields.Many2one('hr.employee', string="Head of Faculty / Dean")
    department_id = fields.Many2one('hr.department', string="Linked HR Department", ondelete='restrict', copy=False)


    def _issued_nim_count(self):
        """How many student numbers already carry this record's code."""
        self.ensure_one()
        return self.env['res.partner'].sudo().with_context(active_test=False).search_count([
            ('nim', 'not in', (False, '')),
            ('program_id.faculty_id', '=', self.id),
        ])

    @api.model_create_multi
    def create(self, vals_list):
        # Checked up front: the loop below creates an hr.department before
        # super() gets to verify the caller may create a faculty at all.
        self.check_access('create')
        cleaned = [dict(vals) for vals in vals_list]
        for vals in cleaned:
            vals['code'] = _normalize_code(vals.get('code')) or _derive_code(vals.get('name'))
        needing = [vals for vals in cleaned if 'name' in vals and not vals.get('department_id')]
        if needing:
            departments = self.env['hr.department'].create([{
                'name': vals['name'],
                'manager_id': vals.get('dean_id', False),
            } for vals in needing])
            for vals, department in zip(needing, departments):
                vals['department_id'] = department.id
        return super().create(cleaned)

    def write(self, vals):
        if 'code' in vals:
            vals = dict(vals)
            normalized = _normalize_code(vals['code'])
            if not normalized:
                raise ValidationError(_("Faculty code cannot be empty."))
            vals['code'] = normalized
            for record in self:
                if normalized != record.code and record._issued_nim_count():
                    raise ValidationError(_(
                        "The code of '%(name)s' can no longer be changed: student "
                        "numbers have already been issued from it."
                    ) % {'name': record.display_name})
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
    _rec_names_search = ['name', 'code']

    _unique_code = models.UniqueIndex(
        "(upper(code)) WHERE code IS NOT NULL",
        "Programme code must be unique: it is what student numbers are built from.",
    )

    _unique_name_case_insensitive = models.UniqueIndex(
        "(lower(name))",
        "Program name must be unique!",
    )

    _unique_department = models.UniqueIndex(
        "(department_id) WHERE department_id IS NOT NULL",
        "Each HR department can only mirror one academic program.",
    )

    name = fields.Char(string='Name', required=True)
    # Immutable short code used as part of the student number (NIM) prefix.
    code = fields.Char(
        string='Code', size=4, copy=False,
        help="Short code used to build student numbers (NIM). Cannot be changed "
             "once a student number has been issued from it.",
    )
    faculty_id = fields.Many2one(
        'academic.faculty', string='Faculty', required=True,
        # Searched by faculty on every programme list and by the jurisdiction
        # record rules in campus_employees.
        index=True,
    )
    head_id = fields.Many2one('hr.employee', string="Head of Program")
    department_id = fields.Many2one('hr.department', string="Linked HR Department", ondelete='restrict', copy=False)


    def _issued_nim_count(self):
        """How many student numbers already carry this record's code."""
        self.ensure_one()
        return self.env['res.partner'].sudo().with_context(active_test=False).search_count([
            ('nim', 'not in', (False, '')),
            ('program_id', '=', self.id),
        ])

    @api.model_create_multi
    def create(self, vals_list):
        # Same reason as on the faculty above.
        self.check_access('create')
        cleaned = [dict(vals) for vals in vals_list]
        for vals in cleaned:
            vals['code'] = _normalize_code(vals.get('code')) or _derive_code(vals.get('name'))
        needing = [vals for vals in cleaned if 'name' in vals and not vals.get('department_id')]
        if needing:
            faculty_ids = {vals['faculty_id'] for vals in needing if vals.get('faculty_id')}
            faculties = {
                faculty.id: faculty
                for faculty in self.env['academic.faculty'].browse(list(faculty_ids))
            }
            departments = self.env['hr.department'].create([{
                'name': vals['name'],
                'parent_id': (
                    faculties[vals['faculty_id']].department_id.id
                    if vals.get('faculty_id') and faculties[vals['faculty_id']].department_id
                    else False
                ),
                'manager_id': vals.get('head_id', False),
            } for vals in needing])
            for vals, department in zip(needing, departments):
                vals['department_id'] = department.id
        programs = super().create(cleaned)
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
        if 'code' in vals:
            vals = dict(vals)
            normalized = _normalize_code(vals['code'])
            if not normalized:
                raise ValidationError(_("Programme code cannot be empty."))
            vals['code'] = normalized
            for record in self:
                if normalized != record.code and record._issued_nim_count():
                    raise ValidationError(_(
                        "The code of '%(name)s' can no longer be changed: student "
                        "numbers have already been issued from it."
                    ) % {'name': record.display_name})
        outgoing_heads = (
            {program.id: program.head_id for program in self}
            if 'head_id' in vals else {}
        )
        outgoing_faculties = (
            {program.id: program.faculty_id for program in self}
            if ('faculty_id' in vals or 'head_id' in vals) else {}
        )
        outgoing_deans = (
            {program.id: program.faculty_id.dean_id for program in self}
            if ('faculty_id' in vals or 'head_id' in vals) else {}
        )
        res = super().write(vals)
        for program in self:
            if program.department_id:
                if 'name' in vals:
                    program.department_id.with_context(campus_mirror_sync=True).name = program.name
                if 'head_id' in vals:
                    program.department_id.with_context(campus_mirror_sync=True).manager_id = program.head_id.id
                if 'faculty_id' in vals:
                    program.department_id.with_context(campus_mirror_sync=True).parent_id = (
                        program.faculty_id.department_id.id if program.faculty_id.department_id else False
                    )
            if 'head_id' in vals:
                old_head = outgoing_heads.get(program.id)
                old_faculty = outgoing_faculties.get(program.id) or program.faculty_id
                old_dean = outgoing_deans.get(program.id)
                if (
                    old_head
                    and old_head != program.head_id
                    and old_dean
                    and old_head.parent_id == old_dean
                    and old_head.department_id != old_faculty.department_id
                    and not self.env['academic.program'].search_count([
                        ('faculty_id', '=', old_faculty.id),
                        ('head_id', '=', old_head.id),
                    ])
                ):
                    old_head.parent_id = False
                if program.head_id:
                    program._set_head_reports_to(program.faculty_id.dean_id)
            elif 'faculty_id' in vals:
                program._set_head_reports_to(program.faculty_id.dean_id, outgoing_deans.get(program.id))
        return res

    def unlink(self):
        departments = self.department_id
        res = super().unlink()
        _drop_linked_departments(departments)
        return res
