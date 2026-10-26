from odoo import _, api, fields, models


class CampusJurisdiction(models.Model):
    """Which faculties and programmes one employee may reach, for one purpose.

    This replaces two parallel sets of four fields on hr.employee -
    ``academic_*`` here and ``pmb_*`` in campus_pmb - that were the same idea
    written twice: the same booleans, the same many2many pair, the same
    onchange, the same mirror, the same form page. Adding a third kind of
    officer meant doing all of it a third time, in whichever module owned them,
    and keeping the three in step by hand.

    One row per (employee, scope). A module that needs a new scope adds a
    selection value and its own record rules; nothing on hr.employee changes.

    This model IS the access-control map, so it is administrator-only in
    security/ir.model.access.csv - including read. The rules that consume it go
    through ``_jurisdiction_domain``, which sudoes, because ir.rule evaluates
    ``domain_force`` as the user themselves
    (odoo/addons/base/models/ir_rule.py:48 passes env.user, not a sudo
    recordset). Reading one's own jurisdiction in order to build one's own
    restriction grants nothing: the result is the narrower domain.
    """

    _name = 'campus.jurisdiction'
    _description = 'Employee Jurisdiction'
    _order = 'employee_id, scope'
    _rec_names_search = ['employee_id.name', 'scope']

    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, ondelete='cascade', index=True,
    )
    scope = fields.Selection(
        selection=[('academic', 'Academic Records')],
        string='Scope', required=True, default='academic',
        help="What this assignment governs. Each module that restricts records "
             "by faculty or programme adds its own scope.",
    )
    all_faculties = fields.Boolean(
        string='All Faculties',
        help="Reaches every faculty, whatever the list below says.",
    )
    faculty_ids = fields.Many2many(
        'academic.faculty', 'campus_jurisdiction_faculty_rel',
        'jurisdiction_id', 'faculty_id', string='Assigned Faculties',
        help="If empty, there is no restriction by faculty - the programme list "
             "alone decides.",
    )
    all_programs = fields.Boolean(
        string='All Programs',
        help="Reaches every programme, whatever the list below says.",
    )
    program_ids = fields.Many2many(
        'academic.program', 'campus_jurisdiction_program_rel',
        'jurisdiction_id', 'program_id', string='Assigned Programs',
        domain="['|', ('faculty_id', 'in', faculty_ids), ('id', '!=', 0)]",
        help="If empty, there is no restriction by programme.",
    )

    _unique_scope_per_employee = models.UniqueIndex(
        "(employee_id, scope)",
        "An employee has one jurisdiction per scope.",
    )

    @api.depends('employee_id', 'scope')
    def _compute_display_name(self):
        labels = dict(self._fields['scope']._description_selection(self.env))
        for record in self:
            record.display_name = '%s - %s' % (
                record.employee_id.name or '', labels.get(record.scope, record.scope or ''),
            )

    @api.onchange('all_faculties')
    def _onchange_all_faculties(self):
        if self.all_faculties:
            self.all_programs = True

    # --- cache -------------------------------------------------------------
    # ir.rule._compute_domain is ormcached on (uid, su, model, mode, context
    # values) only - see ir_rule.py:137 - so nothing here is part of the key.
    # Without clearing it, revoking a faculty kept working for the life of the
    # worker process: the officer went on reading and writing the records they
    # had just lost, for an unbounded window that differed per worker and so
    # looked intermittent.

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env.registry.clear_cache()
        return records

    def write(self, vals):
        res = super().write(vals)
        self.env.registry.clear_cache()
        return res

    def unlink(self):
        res = super().unlink()
        self.env.registry.clear_cache()
        return res

    def _domain_for(self, program_path):
        """Turn this assignment into a record-rule domain.

        An empty list means "no restriction on that dimension", which is what
        the field help promises. Written inline in domain_force, the two
        dimensions were AND'ed as ``in []`` whenever a list was left empty, so
        an officer given a whole faculty but no specific programme matched
        nothing at all - the exact opposite of the intent.

        Fails closed: an employee with no assignment, or a user with no employee
        record, is granted nothing rather than everything.

        :param program_path: path from the target model to academic.program,
            e.g. 'program_id' on academic.krs, 'student_id.program_id' on
            academic.khs.
        """
        self.ensure_one() if self else None
        if not self:
            return [(0, '=', 1)]
        record = self[:1]
        if not (record.all_faculties or record.all_programs
                or record.faculty_ids or record.program_ids):
            return [(0, '=', 1)]

        domain = []
        if not record.all_faculties and record.faculty_ids:
            domain.append(('%s.faculty_id' % program_path, 'in', record.faculty_ids.ids))
        if not record.all_programs and record.program_ids:
            domain.append((program_path, 'in', record.program_ids.ids))
        # A bare list of leaves is AND'ed by Odoo. Empty means both dimensions
        # are unrestricted, which is "everything".
        return domain or [(1, '=', 1)]
