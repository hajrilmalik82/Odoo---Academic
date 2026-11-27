from odoo import _, api, fields, models, Command
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain


def _expand_implied_groups(groups):
    """Return ``groups`` plus every group transitively implied by them."""
    seen = groups
    frontier = groups
    while frontier:
        next_groups = frontier.mapped('implied_ids') - seen
        seen |= next_groups
        frontier = next_groups
    return seen


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    _unique_nidn = models.UniqueIndex(
        "(nidn) WHERE nidn IS NOT NULL AND nidn <> ''",
        "NIDN must be unique across employees.",
    )

    _HR_OR_CAMPUS_GROUPS = (
        "hr.group_hr_user,"
        "campus_core.group_campus_lecturer,"
        "campus_core.group_campus_academic_staff"
    )

    # Odoo 19 delegates organizational fields (department_id, job_id,
    # work_location_id, resource_calendar_id) to hr.version via version_id,
    # and gates mail/activity chatter fields on hr.group_hr_user. Sensitive
    # private and contract fields carry their own hr.group_hr_user/manager
    # guards, so widening version_id and chatter fields lets Lecturers and
    # Academic Staff open employee views and chatter without HR Officer rights.
    version_id = fields.Many2one(groups=_HR_OR_CAMPUS_GROUPS)
    message_main_attachment_id = fields.Many2one(groups=_HR_OR_CAMPUS_GROUPS)
    activity_ids = fields.One2many(groups=_HR_OR_CAMPUS_GROUPS)
    activity_state = fields.Selection(groups=_HR_OR_CAMPUS_GROUPS)
    activity_user_id = fields.Many2one(groups=_HR_OR_CAMPUS_GROUPS)
    activity_type_id = fields.Many2one(groups=_HR_OR_CAMPUS_GROUPS)
    activity_type_icon = fields.Char(groups=_HR_OR_CAMPUS_GROUPS)
    activity_date_deadline = fields.Date(groups=_HR_OR_CAMPUS_GROUPS)
    my_activity_date_deadline = fields.Date(groups=_HR_OR_CAMPUS_GROUPS)
    activity_summary = fields.Char(groups=_HR_OR_CAMPUS_GROUPS)
    activity_exception_decoration = fields.Selection(groups=_HR_OR_CAMPUS_GROUPS)
    activity_exception_icon = fields.Char(groups=_HR_OR_CAMPUS_GROUPS)
    message_is_follower = fields.Boolean(groups=_HR_OR_CAMPUS_GROUPS)
    message_follower_ids = fields.One2many(groups=_HR_OR_CAMPUS_GROUPS)
    message_partner_ids = fields.Many2many(groups=_HR_OR_CAMPUS_GROUPS)
    message_ids = fields.One2many(groups=_HR_OR_CAMPUS_GROUPS)
    message_needaction = fields.Boolean(groups=_HR_OR_CAMPUS_GROUPS)
    message_needaction_counter = fields.Integer(groups=_HR_OR_CAMPUS_GROUPS)
    message_has_error = fields.Boolean(groups=_HR_OR_CAMPUS_GROUPS)
    message_has_error_counter = fields.Integer(groups=_HR_OR_CAMPUS_GROUPS)
    message_attachment_count = fields.Integer(groups=_HR_OR_CAMPUS_GROUPS)

    # 'pmb' is NOT listed here. It is added by campus_pmb through
    # selection_add, together with the action, the menu and the group it maps
    # to. This module must not depend on campus_pmb - campus_pmb depends on it -
    # so a role that only means something once campus_pmb is installed belongs
    # over there. Installed on its own, campus_employees used to offer a PMB
    # Staff role that granted no group and a PMB Staff menu that opened an
    # action that did not exist.
    academic_role = fields.Selection([
        ('lecturer', 'Lecturer'),
        ('academic', 'Academic Staff (TU)')
    ], string="Academic Role", store=True, tracking=True, index=True, copy=False)
    nidn = fields.Char(
        string="NIDN",
        copy=False,
        index='btree_not_null',
        help="National lecturer identification number (Nomor Induk Dosen Nasional).",
    )
    academic_rank = fields.Selection([
        ('asisten_ahli', 'Asisten Ahli'),
        ('lektor', 'Lektor'),
        ('lektor_kepala', 'Lektor Kepala'),
        ('guru_besar', 'Guru Besar')
    ], string="Academic Rank")
    faculty_id = fields.Many2one('academic.faculty', string="Faculty", index=True)
    program_id = fields.Many2one(
        'academic.program', 
        string="Program", 
        domain="[('faculty_id', '=', faculty_id)]",
        index=True,
    )

    # NOTE: the PMB jurisdiction fields (pmb_all_faculties, pmb_faculty_ids,
    # pmb_all_programs, pmb_program_ids) now live in campus_pmb, beside the
    # record rule that reads them. Declaring them here forced this module to
    # depend on campus_pmb while campus_pmb already depended on it.

    # Row-level security jurisdiction.
    #
    # One row per purpose, on campus.jurisdiction. This used to be four fields
    # here (academic_*) and four more in campus_pmb (pmb_*) - the same booleans,
    # the same many2many pair, the same onchange and the same form page, written
    # twice. Protection moved with them: campus.jurisdiction is administrator-
    # only in its ACL, including read, which is a stronger and simpler guard
    # than groups= on eight separate fields.
    jurisdiction_ids = fields.One2many(
        'campus.jurisdiction', 'employee_id', string='Jurisdiction',
        help="Which faculties and programmes this employee may reach, per purpose.",
    )

    # --- what is attached to this person ----------------------------------
    #
    # The same five links the move guard refuses a move over, shown as numbers
    # on the employee form. A refusal that names six schedules is only half an
    # answer; these are the other half - the way to go and look at them.
    #
    # compute_sudo: an HR officer may read a personnel record without any campus
    # group at all, and a count that silently dropped to zero for them would be
    # worse than no count. Opening the button still applies their own rights.
    #
    # No @api.depends, deliberately. The records that point here live on four
    # unrelated models with no inverse relation to depend ON, and declaring
    # One2many fields purely to have something to depend on would put four
    # loaded relations on every employee read. The cost is that the numbers are
    # fresh per read rather than reactive: a form already open does not update
    # them until it is reloaded, which is also when anyone would look.

    advisee_count = fields.Integer(
        string="Students Advised", compute='_compute_campus_links', compute_sudo=True)
    schedule_count = fields.Integer(
        string="Weekly Schedules", compute='_compute_campus_links', compute_sudo=True)
    session_count = fields.Integer(
        string="Class Sessions", compute='_compute_campus_links', compute_sudo=True)
    dean_of_faculty_id = fields.Many2one(
        'academic.faculty', string="Dean of",
        compute='_compute_campus_links', compute_sudo=True)
    head_of_program_id = fields.Many2one(
        'academic.program', string="Head of Programme",
        compute='_compute_campus_links', compute_sudo=True)

    def _count_pointing_here(self, model, field_name, employees):
        """How many records of `model` point at each employee, in one query."""
        groups = self.env[model].sudo()._read_group(
            [(field_name, 'in', employees.ids)],
            groupby=[field_name],
            aggregates=['__count'],
        )
        return {employee.id: count for employee, count in groups}

    def _compute_campus_links(self):
        # Defaults first. A record being created carries a NewId rather than an
        # integer, nothing can point at it yet, and feeding that id to a domain
        # would break the query for the whole batch.
        for employee in self:
            employee.advisee_count = 0
            employee.schedule_count = 0
            employee.session_count = 0
            employee.dean_of_faculty_id = False
            employee.head_of_program_id = False

        saved = self.browse([eid for eid in self.ids if isinstance(eid, int)])
        if not saved:
            return

        advisees = self._count_pointing_here('res.partner', 'academic_advisor_id', saved)
        schedules = self._count_pointing_here('academic.class.schedule', 'lecturer_id', saved)
        sessions = self._count_pointing_here('academic.class.session', 'lecturer_id', saved)
        deans = {
            faculty.dean_id.id: faculty.id
            for faculty in self.env['academic.faculty'].sudo().search([('dean_id', 'in', saved.ids)])
        }
        heads = {
            program.head_id.id: program.id
            for program in self.env['academic.program'].sudo().search([('head_id', 'in', saved.ids)])
        }

        for employee in saved:
            employee.advisee_count = advisees.get(employee.id, 0)
            employee.schedule_count = schedules.get(employee.id, 0)
            employee.session_count = sessions.get(employee.id, 0)
            employee.dean_of_faculty_id = deans.get(employee.id, False)
            employee.head_of_program_id = heads.get(employee.id, False)

    def _action_pointing_here(self, name, model, field_name):
        """Open the records behind a counter, read-and-edit but never create.

        'create': False on all three, deliberately. None of these records is
        born here. A student arrives through the admissions flow in campus_pmb,
        which is what issues their NIM; a weekly schedule belongs to a class and
        is meaningless without one; a session is generated from a schedule. New
        on these lists offered a shortcut past all of that, and the record it
        made would have been missing the thing that gives it meaning.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': 'list,form',
            'domain': [(field_name, '=', self.id)],
            'context': dict(self.env.context, create=False),
        }

    def action_open_advisees(self):
        return self._action_pointing_here(
            _("Students Advised"), 'res.partner', 'academic_advisor_id')

    def action_assign_advisees(self):
        """Choosing among the students who already exist - what New used to
        pretend to offer."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Assign Students"),
            'res_model': 'campus.advisee.assign',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_advisor_id': self.id},
        }

    def action_open_schedules(self):
        return self._action_pointing_here(
            _("Weekly Schedules"), 'academic.class.schedule', 'lecturer_id',
        )

    def action_open_sessions(self):
        return self._action_pointing_here(
            _("Class Sessions"), 'academic.class.session', 'lecturer_id',
        )

    # --- onchange ---------------------------------------------------------
    # Odoo's own ordering convention: every field declaration first, then the
    # onchange methods. These two used to sit in the middle of the field list.

    @api.onchange('faculty_id')
    def _onchange_faculty_id_clear_program(self):
        if self.program_id and self.program_id.faculty_id != self.faculty_id:
            self.program_id = False

    @api.constrains('faculty_id', 'program_id')
    def _check_program_belongs_to_faculty(self):
        for employee in self:
            if employee.program_id and not employee.faculty_id:
                raise ValidationError(_(
                    "Faculty is required when assigning Program '%(program)s'.",
                    program=employee.program_id.display_name,
                ))
            if (
                employee.program_id
                and employee.faculty_id
                and employee.program_id.faculty_id != employee.faculty_id
            ):
                raise ValidationError(_(
                    "Program '%(program)s' does not belong to Faculty '%(faculty)s'.",
                    program=employee.program_id.display_name,
                    faculty=employee.faculty_id.display_name,
                ))

    @api.onchange('job_id')
    def _onchange_job_id_academic(self):
        # Assigned unconditionally: the job position decides the campus role.
        # Setting it only when the new position carried one left the previous
        # value behind, so moving an employee from a lecturer position to an
        # ordinary one kept academic_role at 'lecturer'. The Lecturer Profile
        # page stayed on a non-academic employee, and saving would have granted
        # them the lecturer group.
        self.academic_role = self.job_id.academic_role or False

    @api.onchange('department_id')
    def _onchange_department_id_sync_manager(self):
        if self.department_id:
            dept_manager = self.department_id.manager_id
            # If there's a manager and it's NOT the current employee
            if dept_manager and dept_manager._origin != self._origin:
                self.parent_id = dept_manager
            # If this employee IS the manager, their boss is the parent department's manager (e.g. Dean)
            elif dept_manager and dept_manager._origin == self._origin:
                parent_mgr = self.department_id.parent_id.manager_id
                if parent_mgr and parent_mgr._origin != self._origin:
                    self.parent_id = parent_mgr

    @api.model
    def _infer_faculty_in_vals_list(self, vals_list):
        """Fill missing/falsy `faculty_id` from `program_id` when `program_id` is written."""
        program_ids = {
            vals['program_id']
            for vals in vals_list
            if vals.get('program_id') and not vals.get('faculty_id')
        }
        if not program_ids:
            return vals_list
        programs = self.env['academic.program'].browse(list(program_ids)).grouped('id')
        result = []
        for vals in vals_list:
            if vals.get('program_id') and not vals.get('faculty_id'):
                prog = programs.get(vals['program_id'])
                if prog and prog.faculty_id:
                    vals = dict(vals, faculty_id=prog.faculty_id.id)
            result.append(vals)
        return result

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get('academic_role') for vals in vals_list):
            self._check_may_grant_academic_groups()
        employees = super().create(self._infer_faculty_in_vals_list(vals_list))
        academic_employees = employees.filtered('academic_role')
        academic_employees._sync_academic_user_role()
        if academic_employees.filtered('user_id'):
            self.env.registry.clear_cache()
        return employees

    def write(self, vals):
        vals = self._infer_faculty_in_vals_list([vals])[0]
        if 'academic_role' in vals:
            target_role = vals['academic_role'] or False
            if any((emp.academic_role or False) != target_role for emp in self):
                self._check_may_grant_academic_groups()
        # Prevent non-admin HR officers who already hold a campus group from
        # hijacking an academic employee's jurisdiction or lecturer/dean identity
        # by reassigning user_id or toggling active.
        if {'user_id', 'active'}.intersection(vals):
            if any(emp.academic_role or emp.sudo().jurisdiction_ids for emp in self):
                self._check_may_grant_academic_groups()

        to_check = self._filtered_moving(vals)
        if 'active' in vals and not vals['active']:
            to_check |= self.filtered('active')
        to_check._assert_nothing_still_attached()

        sync_needed = {'academic_role', 'user_id', 'active'}.intersection(vals)
        cache_needed = sync_needed or ('company_id' in vals)
        had_role = self.filtered('academic_role') if cache_needed else self.browse()
        had_jurisdiction = self.filtered(lambda e: e.sudo().jurisdiction_ids) if cache_needed else self.browse()
        previous_users = (had_role | had_jurisdiction).mapped('user_id') if cache_needed else self.env['res.users']

        stale = self.browse()
        if 'faculty_id' in vals and 'program_id' not in vals:
            target_faculty = vals['faculty_id'] or False
            stale = self.filtered(
                lambda emp: emp.program_id and emp.program_id.faculty_id.id != target_faculty
            )

        if stale:
            rest = self - stale
            res = super(HrEmployee, stale).write(dict(vals, program_id=False))
            if rest:
                res = res and super(HrEmployee, rest).write(vals)
        else:
            res = super().write(vals)

        # If a lecturer's faculty/program was filled in from empty, ensure any
        # pre-existing schedules or sessions still match the assigned unit.
        if 'faculty_id' in vals or 'program_id' in vals:
            assigned_schedules = self.env['academic.class.schedule'].sudo().search([
                ('lecturer_id', 'in', self.ids),
            ])
            if assigned_schedules:
                assigned_schedules._check_lecturer_eligible()
            assigned_sessions = self.env['academic.class.session'].sudo().search([
                ('lecturer_id', 'in', self.ids),
            ])
            if assigned_sessions:
                assigned_sessions._check_lecturer_eligible()

        if sync_needed:
            affected = had_role | self.filtered('academic_role')
            affected._sync_academic_user_role(extra_users=previous_users)
        if cache_needed and (had_role or had_jurisdiction or self.filtered('academic_role')):
            self.env.registry.clear_cache()
        return res

    def unlink(self):
        if any(emp.academic_role or emp.sudo().jurisdiction_ids for emp in self):
            self._check_may_grant_academic_groups()
        self.with_context(_campus_unlink_check=True)._assert_nothing_still_attached()
        had_academic_or_juris = bool(self.filtered(lambda e: e.academic_role or e.sudo().jurisdiction_ids))
        affected_users = self.filtered('academic_role').mapped('user_id')
        res = super().unlink()
        if affected_users:
            self.env['hr.employee']._sync_academic_user_role(extra_users=affected_users)
        if had_academic_or_juris:
            self.env.registry.clear_cache()
        return res

    # --- moving somebody between units ------------------------------------

    _MOVE_FIELDS = ('faculty_id', 'program_id', 'academic_role')

    def _filtered_moving(self, vals):
        """Those of these employees that `vals` would actually move.

        Checked here rather than in an @api.constrains for two reasons. A
        constraint cannot see the value a field held before the write, so it
        cannot tell a move from a write that stores the value already there -
        and an import or a re-save would then be refused for changing nothing.
        And it fires after the write, while the point of this rule is to stop
        the change from happening.

        Filling a profile in for the first time is not a move. The demo data
        relies on it, and so does ordinary use: campus_core creates the
        teaching schedule, and campus_employees only afterwards says which
        faculty and programme those lecturers belong to. A guard that counted
        an empty-to-set write as a move would refuse its own fixtures.
        """
        moving = self.browse()
        for employee in self:
            for name in self._MOVE_FIELDS:
                if name not in vals:
                    continue
                current = employee[name]
                if not current:
                    continue
                before = current.id if name.endswith('_id') else current
                if vals[name] != before:
                    moving |= employee
                    break
        return moving

    def _what_still_points_by_employee(self):
        """Return ``{employee_id: [messages]}`` across ``self`` using batched queries.

        During moves or archiving, only active commitments block (active academic
        years for schedules, active/future sessions, and non-graduated/non-dropout
        advisees) so lecturers can retire or transfer after a semester ends.
        During permanent deletion (``_campus_unlink_check``), all historical
        references block to preserve referential integrity.
        """
        saved = self.browse([eid for eid in self.ids if isinstance(eid, int)])
        if not saved:
            return {}
        include_history = bool(self.env.context.get('_campus_unlink_check'))
        by_emp = {emp.id: [] for emp in saved}

        for faculty in self.env['academic.faculty'].sudo().search([('dean_id', 'in', saved.ids)]):
            by_emp[faculty.dean_id.id].append(_("Dean of %(faculty)s", faculty=faculty.name))

        for program in self.env['academic.program'].sudo().search([('head_id', 'in', saved.ids)]):
            by_emp[program.head_id.id].append(_("Head of %(program)s", program=program.name))

        schedule_domain = [('lecturer_id', 'in', saved.ids)]
        if not include_history:
            schedule_domain.append(('class_id.academic_year_id.active', '=', True))
        schedules_by_emp = {}
        for schedule in self.env['academic.class.schedule'].sudo().search(schedule_domain):
            schedules_by_emp.setdefault(schedule.lecturer_id.id, []).append(schedule)
        for emp_id, schedules in schedules_by_emp.items():
            subjects = sorted({
                sched.class_id.subject_id.name
                for sched in schedules
                if sched.class_id.subject_id.name
            })
            by_emp[emp_id].append(_(
                "Teaching %(count)s weekly schedule(s): %(subjects)s",
                count=len(schedules),
                subjects=", ".join(subjects) or "-",
            ))

        session_domain = [('lecturer_id', 'in', saved.ids)]
        if not include_history:
            session_domain += [
                '|',
                ('class_id.academic_year_id.active', '=', True),
                ('end_datetime', '>=', fields.Datetime.now()),
            ]
        session_groups = self.env['academic.class.session'].sudo()._read_group(
            session_domain, groupby=['lecturer_id'], aggregates=['__count'],
        )
        for emp, count in session_groups:
            if count:
                by_emp[emp.id].append(_("Named on %(count)s class session(s)", count=count))

        students_by_emp = {}
        partner_domain = [('academic_advisor_id', 'in', saved.ids)]
        if not include_history:
            partner_domain.append(('student_status', 'in', ('active', 'leave')))
        archived_aware_partners = self.env['res.partner'].sudo().with_context(active_test=False)
        for student in archived_aware_partners.search(partner_domain):
            students_by_emp.setdefault(student.academic_advisor_id.id, []).append(student.name or '-')
        for emp_id, names in students_by_emp.items():
            by_emp[emp_id].append(_(
                "Academic advisor to %(count)s student(s): %(names)s",
                count=len(names),
                names=", ".join(names[:5]) + ("..." if len(names) > 5 else ""),
            ))

        return by_emp

    def _what_still_points_here(self):
        """Everything that would be left dangling, named so a user can act.

        sudo() throughout: an HR officer editing a personnel record is not
        required to have read access to the institution tree or to the student
        list, and whether a move is safe must not depend on whether they happen
        to have it.
        """
        self.ensure_one()
        return self._what_still_points_by_employee().get(self.id, [])

    def _assert_nothing_still_attached(self):
        """Refuse a move while anything still points at the person.

        Everything is collected before anything is raised: being told about one
        class, fixing it, and then being told about a second is a worse
        experience than being handed the whole list once.
        """
        if not self:
            return
        by_emp = self._what_still_points_by_employee()
        for employee in self:
            attached = by_emp.get(employee.id, [])
            if not attached:
                continue
            raise ValidationError(_(
                "%(person)s cannot be moved to another faculty or programme yet."
                " These still point at them:\n\n%(items)s\n\n"
                "Reassign or clear them first, then make this change.",
                person=employee.name,
                items="\n".join("  - %s" % item for item in attached),
            ))

    def _jurisdiction(self, scope):
        """This employee's assignment for one purpose, or an empty recordset."""
        employees = self.sudo()
        if not employees:
            return self.env['campus.jurisdiction']
        return employees.jurisdiction_ids.filtered(lambda row: row.scope == scope)[:1]

    def _jurisdiction_domain(self, scope, program_path):
        """Record-rule domain across all matching active employee records."""
        employees = self.sudo()
        if not employees:
            return [(0, '=', 1)]
        rows = employees.jurisdiction_ids.filtered(lambda row: row.scope == scope)
        if not rows:
            return [(0, '=', 1)]
        if len(rows) == 1:
            return rows._domain_for(program_path)
        domains = [row._domain_for(program_path) for row in rows]
        return list(Domain.OR([Domain(d) for d in domains]))

    def _academic_jurisdiction_domain(self, program_path='program_id'):
        """Domain for an Academic Staff member, called from ir.rule.domain_force."""
        return self._jurisdiction_domain('academic', program_path)

    def _check_may_grant_academic_groups(self):
        """Campus group membership stays an administrator's decision.

        _sync_academic_user_role grants those groups through sudo(), and that
        sudo is precisely what normally stops a non-administrator touching
        group_ids. Odoo gives hr.group_hr_user full write on hr.employee, so
        without this check an HR officer could set academic_role on their own
        employee record and hand themselves group_campus_academic_staff, which
        carries full CRUD on every academic model and on res.partner, delete
        included.
        """
        if self.env.su or self.env.user.has_group('campus_core.group_campus_administrator'):
            return
        raise AccessError(_(
            "Only a Campus Administrator can change an employee's Academic Role, "
            "because it grants campus access groups."
        ))

    def _academic_role_groups(self):
        """Map academic_role to the campus group it grants.

        A method, like the jurisdiction scope selection, so campus_pmb can add its own role
        with super() instead of this module reaching across to an xmlid it is
        not allowed to depend on.
        """
        return {
            'lecturer': self.env.ref('campus_core.group_campus_lecturer'),
            'academic': self.env.ref('campus_core.group_campus_academic_staff'),
        }

    def _sync_academic_user_role(self, extra_users=None):
        """Recompute campus groups for affected users from active employee records.

        Recomputing from active employees ensures clearing user_id, reassigning
        to a different user, archiving, or deleting an employee revokes groups
        that no other active employee record still grants.
        """
        role_groups = self._academic_role_groups()
        academic_groups = self.env['res.groups'].union(*role_groups.values())
        users = (self.mapped('user_id') | (extra_users or self.env['res.users'])).filtered(bool)
        if not users:
            return

        active_by_user = {}
        active_employees = self.env['hr.employee'].sudo().with_context(active_test=True).search([
            ('user_id', 'in', users.ids),
            ('academic_role', '!=', False),
        ])
        for employee in active_employees:
            group = role_groups.get(employee.academic_role)
            if group:
                active_by_user[employee.user_id.id] = (
                    active_by_user.get(employee.user_id.id, self.env['res.groups']) | group
                )

        empty = self.env['res.groups']
        for user in users:
            keep = active_by_user.get(user.id, empty)
            # Read under sudo: comparing another user's group membership.
            current = user.sudo().group_ids
            # Preserve any academic group implied by a higher non-managed group
            # (for example campus_core.group_campus_administrator implies
            # lecturer, academic staff, and PMB). Unlinking an implied group
            # triggers Odoo's reverse-implication cascade and silently demotes
            # the administrator.
            retained_by_implication = _expand_implied_groups(current - academic_groups)
            to_add = keep - current
            to_remove = (academic_groups - keep - retained_by_implication) & current
            if not to_add and not to_remove:
                continue

            self._check_may_grant_academic_groups()
            user.sudo().write({
                'group_ids': [Command.unlink(group.id) for group in to_remove]
                             + [Command.link(group.id) for group in to_add],
            })

    # Odoo 19's hr / hr_homeworking computes read hr.group_hr_user-gated fields
    # (birthday, exceptional_location_id) without sudo() on kanban/list/form
    # views. Running those computes under sudo() lets Lecturers and Academic
    # Staff open employee views cleanly without granting hr.group_hr_user.
    def _compute_birthday_public_display_string(self):
        return super(HrEmployee, self.sudo())._compute_birthday_public_display_string()

    def _compute_work_location_name(self):
        if hasattr(super(), '_compute_work_location_name'):
            return super(HrEmployee, self.sudo())._compute_work_location_name()

    def _compute_work_location_type(self):
        if hasattr(super(), '_compute_work_location_type'):
            return super(HrEmployee, self.sudo())._compute_work_location_type()

class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    # Deliberately not stored, like every other mirror on this model. The parent
    # is an _auto = False model whose table is a SQL view joining hr_employee to
    # hr_version (addons/hr/models/hr_employee_public.py:194-203), and PostgreSQL
    # refuses to update a view built from more than one table. Storing these two
    # folded them into that view's SELECT via _get_fields(), so every write of
    # academic_role or nidn on an existing employee queued a recompute here and
    # died at flush with "cannot update view hr_employee_public", taking the
    # whole transaction with it. Creating an employee happened to survive, which
    # is why the Lecturer and PMB forms looked fine.
    # Nothing is lost by dropping it: fields.py:636-638 grants a non-stored
    # related field its own search, which a stored one on a view never had.
    academic_role = fields.Selection(related='employee_id.academic_role', readonly=True)
    nidn = fields.Char(related='employee_id.nidn', readonly=True)
    academic_rank = fields.Selection(related='employee_id.academic_rank', readonly=True)
    faculty_id = fields.Many2one(related='employee_id.faculty_id', readonly=True)
    program_id = fields.Many2one(related='employee_id.program_id', readonly=True)

    # The pmb_* mirrors moved to campus_pmb alongside their source fields.

    # The four academic_* jurisdiction fields are deliberately NOT mirrored
    # here. They are the access-control map, nothing reads them through
    # hr.employee.public - the record rules go through user.employee_id, and
    # env.user is already sudoed (odoo/orm/environments.py: the `user` cached
    # property returns a su recordset) - and mirroring row-level security
    # configuration onto the model every internal user can read is the wrong
    # default even with a groups= gate on top.
