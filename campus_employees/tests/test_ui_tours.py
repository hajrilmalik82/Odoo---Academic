from odoo.tests.common import tagged

from odoo.addons.campus_core.tests.common import TAG, CampusHttpCommon


@tagged('post_install', '-at_install', 'campus_ui')
class TestCampusEmployeesUiTours(CampusHttpCommon):
    """Comprehensive browser UI tours for campus_employees views, kanban, and website showcase."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        internal = cls.env.ref('base.group_user')
        cls.lecturer_user = cls.env['res.users'].create({
            'name': '%s Dosen Employees UI' % TAG,
            'login': 'zz.ui.dosen.emp@contoh.test',
            'password': cls.PORTAL_PASSWORD,
            'group_ids': [(6, 0, [
                internal.id,
                cls.env.ref('campus_core.group_campus_lecturer').id,
            ])],
        })
        cls.hr_admin_user = cls.env['res.users'].create({
            'name': '%s Admin Employees UI' % TAG,
            'login': 'zz.ui.admin.emp@contoh.test',
            'password': cls.PORTAL_PASSWORD,
            'group_ids': [(6, 0, [
                internal.id,
                cls.env.ref('hr.group_hr_manager').id,
                cls.env.ref('campus_core.group_campus_administrator').id,
            ])],
        })
        cls.staff_emp = cls.env['hr.employee'].create({
            'name': '%s Staf TU UI' % TAG,
            'academic_role': 'academic',
        })
        cls.department = cls.env['hr.department'].create({
            'name': '%s Jurusan Informatika UI' % TAG,
        })

    def test_01_lecturer_without_hr_opens_lecturers_form_and_chatter_ui_tour(self):
        action = self.env.ref('campus_employees.action_hr_employee_lecturer')
        self.start_tour(
            '/odoo/action-%d' % action.id,
            'campus_employees_lecturer_views_ui_tour',
            login=self.lecturer_user.login,
        )

    def test_02_lecturer_without_hr_opens_academic_staff_kanban_ui_tour(self):
        action = self.env.ref('campus_employees.action_hr_employee_academic_staff')
        self.start_tour(
            '/odoo/action-%d' % action.id,
            'campus_employees_kanban_ui_tour',
            login=self.lecturer_user.login,
        )

    def test_03_admin_switches_lecturer_list_kanban_and_form_ui_tour(self):
        action = self.env.ref('campus_employees.action_hr_employee_lecturer')
        self.start_tour(
            '/odoo/action-%d' % action.id,
            'campus_employees_admin_kanban_switch_ui_tour',
            login=self.hr_admin_user.login,
        )

    def test_04_admin_opens_academic_staff_and_department_forms_ui_tour(self):
        staff_action = self.env.ref('campus_employees.action_hr_employee_academic_staff')
        self.start_tour(
            '/odoo/action-%d' % staff_action.id,
            'campus_employees_kanban_to_form_ui_tour',
            login=self.hr_admin_user.login,
        )
        dept_action = self.env.ref('hr.hr_department_kanban_action')
        self.start_tour(
            '/odoo/action-%d' % dept_action.id,
            'campus_employees_kanban_ui_tour',
            login=self.hr_admin_user.login,
        )

    def test_05_public_homepage_employees_tab_ui_tour(self):
        self.start_tour('/', 'campus_employees_homepage_tab_ui_tour')
