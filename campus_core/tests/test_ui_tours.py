from odoo.tests.common import tagged

from odoo.addons.campus_core.tests.common import TAG, CampusHttpCommon


@tagged('post_install', '-at_install', 'campus_ui')
class TestCampusCoreUiTours(CampusHttpCommon):
    """Comprehensive browser UI tours for all campus_core views, workflows, and security."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        internal = cls.env.ref('base.group_user')
        cls.accountant_user = cls.env['res.users'].create({
            'name': '%s Akuntan UI' % TAG,
            'login': 'zz.ui.akuntan@contoh.test',
            'password': cls.PORTAL_PASSWORD,
            'group_ids': [(6, 0, [internal.id])],
        })
        cls.lecturer_user = cls.env['res.users'].create({
            'name': '%s Dosen UI' % TAG,
            'login': 'zz.ui.dosen.core@contoh.test',
            'password': cls.PORTAL_PASSWORD,
            'group_ids': [(6, 0, [
                internal.id,
                cls.env.ref('campus_core.group_campus_lecturer').id,
            ])],
        })
        cls.admin_user = cls.env['res.users'].create({
            'name': '%s Admin UI' % TAG,
            'login': 'zz.ui.admin.core@contoh.test',
            'password': cls.PORTAL_PASSWORD,
            'group_ids': [(6, 0, [
                internal.id,
                cls.env.ref('campus_core.group_campus_administrator').id,
            ])],
        })
        cls.course_package = cls.env['academic.course.package'].create({
            'name': '%s Paket Semester 1' % TAG,
            'program_id': cls.program.id,
            'academic_year_id': cls.year.id,
            'semester': '1',
            'line_ids': [(0, 0, {'subject_id': cls.subject_a.id})],
        })
        cls.credit_limit = cls.env['academic.credit.limit'].search([], limit=1) or cls.env['academic.credit.limit'].create({
            'min_cgpa': 3.75,
            'max_credits': 24,
        })
        cls.grade_scale = cls.env['academic.grade.scale'].search([], limit=1) or cls.env['academic.grade.scale'].create({
            'min_score': 99.0,
            'letter': 'A+',
            'grade_point': 4.0,
        })
        today_dt = cls.klass.start_date
        cls.class_session = cls.env['academic.class.session'].create({
            'name': '%s Sesi 1' % TAG,
            'class_id': cls.klass.id,
            'start_datetime': '%s 08:00:00' % today_dt,
            'end_datetime': '%s 10:00:00' % today_dt,
        })

    def _open_action_list_to_form(self, action_xmlid, login):
        action = self.env.ref(action_xmlid)
        self.start_tour(
            '/odoo/action-%d' % action.id,
            'campus_core_list_to_form_ui_tour',
            login=login,
        )

    def test_01_plain_internal_user_opens_student_contact_ui_tour(self):
        self.start_tour(
            '/odoo/res.partner/%d' % self.student.id,
            'campus_core_accountant_contact_ui_tour',
            login=self.accountant_user.login,
        )

    def test_02_teaching_lecturer_grades_khs_ui_tour(self):
        self.schedule.lecturer_id = self.advisor
        self.advisor.user_id = self.lecturer_user
        krs = self._make_krs()
        krs.action_submit()
        krs.action_approve()
        krs.action_lock()
        khs = self.env['academic.khs'].search([
            ('student_id', '=', self.student.id),
            ('academic_year_id', '=', self.year.id),
        ], limit=1)
        self.start_tour(
            '/odoo/academic.khs/%d' % khs.id,
            'campus_core_lecturer_khs_grading_ui_tour',
            login=self.lecturer_user.login,
        )
        line = khs.line_ids[:1]
        line.invalidate_recordset(['numeric_grade', 'is_graded', 'letter_grade'])
        self.assertEqual(line.numeric_grade, 85.0)
        self.assertTrue(line.is_graded)

    def test_03_lecturer_opens_classes_schedules_sessions_ui_tour(self):
        self.schedule.lecturer_id = self.advisor
        self.advisor.user_id = self.lecturer_user
        self.class_session.lecturer_id = self.advisor
        for xmlid in (
            'campus_core.action_academic_class',
            'campus_core.action_academic_class_schedule',
        ):
            self._open_action_list_to_form(xmlid, self.lecturer_user.login)
        session_action = self.env.ref('campus_core.action_academic_class_session')
        self.start_tour(
            '/odoo/action-%d' % session_action.id,
            'campus_core_calendar_to_list_form_ui_tour',
            login=self.lecturer_user.login,
        )

    def test_04_admin_krs_workflow_ui_tour(self):
        krs = self._make_krs()
        self.start_tour(
            '/odoo/academic.krs/%d' % krs.id,
            'campus_core_krs_workflow_ui_tour',
            login=self.admin_user.login,
        )
        krs.invalidate_recordset(['state'])
        self.assertEqual(krs.state, 'locked')

    def test_05_admin_students_list_form_and_stat_buttons_ui_tour(self):
        self._make_krs()
        action = self.env.ref('campus_core.action_res_partner_student')
        self.start_tour(
            '/odoo/action-%d' % action.id,
            'campus_core_student_stat_buttons_ui_tour',
            login=self.admin_user.login,
        )

    def test_06_admin_khs_and_course_packages_ui_tour(self):
        krs = self._make_krs()
        krs.action_submit()
        krs.action_approve()
        krs.action_lock()
        for xmlid in (
            'campus_core.action_academic_khs',
            'campus_core.action_academic_course_package',
        ):
            self._open_action_list_to_form(xmlid, self.admin_user.login)

    def test_07_admin_institution_and_curriculum_views_ui_tour(self):
        for xmlid in (
            'campus_core.action_academic_faculty',
            'campus_core.action_academic_program',
            'campus_core.action_academic_subject',
            'campus_core.action_academic_year',
        ):
            self._open_action_list_to_form(xmlid, self.admin_user.login)

    def test_08_admin_facilities_and_policies_views_ui_tour(self):
        for xmlid in (
            'campus_core.action_campus_building',
            'campus_core.action_campus_room',
        ):
            self._open_action_list_to_form(xmlid, self.admin_user.login)
        for xmlid in (
            'campus_core.action_academic_credit_limit',
            'campus_core.action_academic_grade_scale',
        ):
            action = self.env.ref(xmlid)
            self.start_tour(
                '/odoo/action-%d' % action.id,
                'campus_core_list_only_ui_tour',
                login=self.admin_user.login,
            )

    def test_09_admin_creates_subject_via_ui_tour(self):
        action = self.env.ref('campus_core.action_academic_faculty')
        self.start_tour(
            '/odoo/action-%d' % action.id,
            'campus_core_create_faculty_ui_tour',
            login=self.admin_user.login,
        )
        created = self.env['academic.faculty'].search([('code', '=', 'ZZUIFAC')], limit=1)
        self.assertTrue(created)
        self.assertEqual(created.name, 'ZZTEST Fakultas UI')
