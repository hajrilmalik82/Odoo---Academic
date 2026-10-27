from odoo.exceptions import AccessError
from odoo.tests.common import tagged

from odoo.addons.campus_core.tests.common import TAG, CampusCommon


@tagged('post_install', '-at_install')
class TestAcademicJurisdiction(CampusCommon):
    """The eight jurisdiction fields ARE the access-control map.

    They decide which students' records an academic staff member reaches, so
    they are restricted to campus administrators and a change to them has to
    take effect at once.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.staff_group = cls.env.ref('campus_core.group_campus_academic_staff')
        cls.admin_group = cls.env.ref('campus_core.group_campus_administrator')
        internal = cls.env.ref('base.group_user')

        cls.staff_user = cls.env['res.users'].create({
            'name': '%s Staf TU' % TAG, 'login': 'zz.staf.tu.test',
            'group_ids': [(6, 0, [internal.id, cls.staff_group.id])],
        })
        cls.staff_employee = cls.env['hr.employee'].create({
            'name': '%s Staf TU' % TAG,
            'academic_role': 'academic',
            'user_id': cls.staff_user.id,
        })
        # A second faculty and programme, so "outside my jurisdiction" is a real
        # place and not just an empty set.
        cls.other_faculty = cls.env['academic.faculty'].create({
            'name': '%s Fakultas Lain' % TAG, 'code': 'ZFL',
        })
        cls.other_program = cls.env['academic.program'].create({
            'name': '%s Prodi Lain' % TAG, 'code': 'ZPL',
            'faculty_id': cls.other_faculty.id,
        })
        # An advisor of the OTHER programme: cls.advisor belongs to cls.program,
        # and an academic advisor shares their advisee's programme.
        cls.other_advisor = cls.env['hr.employee'].create({
            'name': '%s Dosen PA Lain' % TAG,
            'academic_role': 'lecturer',
            'faculty_id': cls.other_faculty.id,
            'program_id': cls.other_program.id,
        })
        cls.other_student = cls.env['res.partner'].create({
            'name': '%s Mahasiswa Lain' % TAG, 'is_student': True,
            'student_status': 'active', 'program_id': cls.other_program.id,
            'academic_advisor_id': cls.other_advisor.id,
        })

    def _visible_krs(self):
        return self.env['academic.krs'].with_user(self.staff_user).search([])

    def _assign(self, **values):
        """Give the staff member a jurisdiction, or change the one they have."""
        existing = self.staff_employee.sudo().jurisdiction_ids.filtered(
            lambda row: row.scope == 'academic',
        )
        if existing:
            existing.write(values)
            return existing
        return self.env['campus.jurisdiction'].sudo().create(dict(
            values, employee_id=self.staff_employee.id, scope='academic',
        ))

    def test_no_jurisdiction_means_nothing_rather_than_everything(self):
        """Fails closed. An unassigned staff member is granted nothing."""
        self._make_krs()
        self.assertFalse(self._visible_krs())

    def test_a_faculty_assignment_scopes_what_is_visible(self):
        mine = self._make_krs()
        theirs = self._make_krs(student=self.other_student, year=self.year_retake,
                                schedules=self.schedule_retake)
        self._assign(faculty_ids=[(6, 0, self.faculty.ids)])
        visible = self._visible_krs()
        self.assertIn(mine, visible)
        self.assertNotIn(theirs, visible)

    def test_revoking_a_jurisdiction_takes_effect_at_once(self):
        """ir.rule._compute_domain is ormcached and the jurisdiction is not part
        of its key, so hr.employee.write has to clear the registry cache itself.
        Without that, a revoked assignment kept working until something
        unrelated happened to clear the cache."""
        krs = self._make_krs()
        assignment = self._assign(faculty_ids=[(6, 0, self.faculty.ids)])
        self.assertIn(krs, self._visible_krs())

        assignment.write({'faculty_ids': [(6, 0, self.other_faculty.ids)]})
        self.assertNotIn(krs, self._visible_krs(), "revocation must not be delayed")

    def test_staff_cannot_widen_their_own_jurisdiction(self):
        """Odoo grants hr.group_hr_user full write on hr.employee, so without a
        guard a staff member could tick All Faculties on their own record and
        reach every student in the university. The guard is now the ACL on
        campus.jurisdiction, which admits campus administrators only."""
        assignment = self._assign(faculty_ids=[(6, 0, self.faculty.ids)])
        with self.assertRaises(AccessError):
            assignment.with_user(self.staff_user).write({'all_faculties': True})

    def test_staff_cannot_even_read_the_map(self):
        """It is the access-control map. Everything that consumes it sudoes."""
        self._assign(faculty_ids=[(6, 0, self.faculty.ids)])
        self.assertFalse(
            self.env['campus.jurisdiction'].with_user(self.staff_user).has_access('read'),
        )

    def test_an_administrator_may_set_it(self):
        admin = self.env['res.users'].create({
            'name': '%s Admin Kampus' % TAG, 'login': 'zz.admin.kampus.test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id, self.admin_group.id])],
        })
        assignment = self._assign()
        assignment.with_user(admin).write({'all_faculties': True})
        self.assertTrue(assignment.sudo().all_faculties)

    def test_one_row_per_scope_per_employee(self):
        self._assign()
        from psycopg2.errors import UniqueViolation
        from odoo.tools import mute_logger
        with mute_logger('odoo.sql_db'), self.assertRaises(UniqueViolation), self.cr.savepoint():
            self.env['campus.jurisdiction'].sudo().create({
                'employee_id': self.staff_employee.id, 'scope': 'academic',
            })
            self.env.flush_all()

    def test_both_scopes_live_on_one_model(self):
        """Academic staff and PMB officers were two parallel sets of four fields
        on hr.employee. A third kind of officer is one selection value now."""
        scopes = dict(self.env['campus.jurisdiction']._fields['scope']._description_selection(self.env))
        self.assertIn('academic', scopes)
        self.assertIn('pmb', scopes)

    def test_the_jurisdiction_is_not_mirrored_onto_the_public_model(self):
        """hr.employee.public is readable by every internal user, so publishing
        the access-control map there was the wrong default."""
        public_fields = self.env['hr.employee.public']._fields
        self.assertNotIn('jurisdiction_ids', public_fields)
        for name in ('academic_all_faculties', 'pmb_all_faculties'):
            self.assertNotIn(name, public_fields)


@tagged('post_install', '-at_install')
class TestCampusRoles(CampusCommon):
    """Who may change what, matching how a campus is actually run.

    BAAK/TU processes study plans and opens the KRS period; curriculum belongs
    to the programme and academic policy to the rectorate. Staff can still READ
    everything, because they answer students' questions about it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        internal = cls.env.ref('base.group_user')
        cls.staff = cls.env['res.users'].create({
            'name': '%s Staf Peran' % TAG, 'login': 'zz.staf.peran.test',
            'group_ids': [(6, 0, [
                internal.id, cls.env.ref('campus_core.group_campus_academic_staff').id,
            ])],
        })

    def _as_staff(self, model):
        return self.env[model].with_user(self.staff)

    def test_staff_may_read_but_not_change_the_curriculum(self):
        self.assertTrue(self._as_staff('academic.subject').has_access('read'))
        self.assertFalse(self._as_staff('academic.subject').has_access('write'))

    def test_staff_may_read_but_not_change_academic_policy(self):
        for model in ('academic.credit.limit', 'academic.grade.scale'):
            with self.subTest(model=model):
                self.assertTrue(self._as_staff(model).has_access('read'))
                self.assertFalse(self._as_staff(model).has_access('write'))

    def test_staff_may_open_and_close_the_krs_period(self):
        """The academic calendar is BAAK's job."""
        self.assertTrue(self._as_staff('academic.year').has_access('write'))
        self.assertFalse(self._as_staff('academic.year').has_access('create'))
        self.assertFalse(self._as_staff('academic.year').has_access('unlink'))

    def test_staff_still_manage_rooms(self):
        self.assertTrue(self._as_staff('campus.room').has_access('create'))

    def test_the_configuration_menu_is_open_to_staff_and_closed_to_lecturers(self):
        menu = self.env.ref('campus_core.menu_academic_configuration')
        groups = menu.group_ids
        self.assertIn(self.env.ref('campus_core.group_campus_academic_staff'), groups)
        self.assertNotIn(self.env.ref('campus_core.group_campus_lecturer'), groups)
