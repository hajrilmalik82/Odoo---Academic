from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


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
    # The previous domain was ['|', ('faculty_id', 'in', faculty_ids),
    # ('id', '!=', 0)]. The second leaf is true of every row, so the OR made
    # the whole domain true: it narrowed nothing while reading as though it
    # did. Conditional, because the two dimensions are AND'ed in _domain_for -
    # see the constraint below for what that costs - and because narrowing
    # unconditionally would leave the list empty whenever no faculty has been
    # assigned, which is a legitimate programme-only jurisdiction.
    program_ids = fields.Many2many(
        'academic.program', 'campus_jurisdiction_program_rel',
        'jurisdiction_id', 'program_id', string='Assigned Programs',
        domain="[('faculty_id', 'in', faculty_ids)]"
               " if faculty_ids and not all_faculties else []",
        help="If empty, there is no restriction by programme.",
    )

    @api.constrains('all_faculties', 'faculty_ids', 'program_ids')
    def _check_programs_lie_inside_the_faculties(self):
        """A programme outside the assigned faculties makes the row useless.

        _domain_for AND's the two dimensions, so an officer given Faculty of
        Engineering plus a Management programme matches nothing at all - no
        faculty error, no warning, simply an empty screen that looks like a
        permissions bug. The domain above steers the dropdown; this holds for
        an import, a server action or a paste into the list view, which is the
        same split as dean_id and head_id in academic_institution.py.
        """
        for record in self:
            if record.all_faculties or not record.faculty_ids:
                continue
            stray = record.program_ids.filtered(
                lambda program: program.faculty_id not in record.faculty_ids
            )
            if stray:
                raise ValidationError(_(
                    "%(programs)s do not belong to the assigned faculties"
                    " (%(faculties)s). An assignment that names both a faculty and"
                    " a programme outside it reaches no records at all: widen the"
                    " faculty list, or drop the programme.",
                    programs=", ".join(stray.mapped('display_name')),
                    faculties=", ".join(record.faculty_ids.mapped('name')),
                ))

    _unique_scope_per_employee = models.UniqueIndex(
        "(employee_id, scope)",
        "An employee has one jurisdiction per scope.",
    )

    @api.depends('employee_id.name', 'scope')
    def _compute_display_name(self):
        labels = dict(self._fields['scope']._description_selection(self.env))
        for record in self:
            record.display_name = '%s - %s' % (
                record.employee_id.name or '', labels.get(record.scope, record.scope or ''),
            )

    def copy(self, default=None):
        raise ValidationError(_(
            "Jurisdiction assignments cannot be duplicated because each employee can only have one row per scope."
        ))

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
        auto_indices = [
            idx for idx, vals in enumerate(vals_list)
            if vals.get('all_faculties') and 'all_programs' not in vals
        ]
        records = super().create(vals_list)
        if auto_indices:
            to_enable = records.browse([
                records[idx].id for idx in auto_indices if not records[idx].program_ids
            ])
            if to_enable:
                super(CampusJurisdiction, to_enable).write({'all_programs': True})
        self.env.registry.clear_cache()
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals.get('all_faculties') and 'all_programs' not in vals:
            # Mirror _onchange_all_faculties when effective program_ids ends up empty.
            with_no_programs = self.filtered(lambda rec: not rec.program_ids and not rec.all_programs)
            if with_no_programs:
                super(CampusJurisdiction, with_no_programs).write({'all_programs': True})
        self.env.registry.clear_cache()
        return res

    def unlink(self):
        res = super().unlink()
        self.env.registry.clear_cache()
        return res

    def _domain_for(self, program_path):
        """Turn this assignment into a record-rule domain.

        Fails closed: an employee with no assignment, or contradictory
        all_faculties / all_programs flags without explicit scope on the other
        dimension, is granted nothing rather than everything.
        """
        if not self:
            return [(0, '=', 1)]
        self.ensure_one()
        if not (self.all_faculties or self.all_programs
                or self.faculty_ids or self.program_ids):
            return [(0, '=', 1)]

        domain = []
        if not self.all_faculties and self.faculty_ids:
            domain.append(('%s.faculty_id' % program_path, 'in', self.faculty_ids.ids))
        if not self.all_programs and self.program_ids:
            domain.append((program_path, 'in', self.program_ids.ids))
        elif self.all_faculties and not self.all_programs and not self.program_ids:
            # Explicit all_faculties=True with all_programs=False and zero selected programs
            # fails closed instead of silently unlocking every program.
            return [(0, '=', 1)]
        elif self.all_programs and not self.all_faculties and not self.faculty_ids:
            # Symmetric guard: all_programs=True with all_faculties=False and zero selected
            # faculties must also fail closed instead of unlocking every faculty.
            return [(0, '=', 1)]
        # A bare list of leaves is AND'ed by Odoo. Empty means both dimensions
        # are explicitly unrestricted (all_faculties=True and all_programs=True).
        return domain or [(1, '=', 1)]

    def _covers_program(self, program):
        """Return whether this single jurisdiction row grants access to ``program``."""
        self.ensure_one()
        if not program:
            return False
        if not (self.all_faculties or self.all_programs
                or self.faculty_ids or self.program_ids):
            return False
        if self.all_faculties and not self.all_programs and not self.program_ids:
            return False
        if self.all_programs and not self.all_faculties and not self.faculty_ids:
            return False
        faculty_ok = self.all_faculties or not self.faculty_ids or program.faculty_id in self.faculty_ids
        program_ok = self.all_programs or not self.program_ids or program in self.program_ids
        return faculty_ok and program_ok
