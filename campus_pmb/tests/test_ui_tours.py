from odoo.tests.common import tagged

from odoo.addons.campus_core.tests.common import TAG, CampusHttpCommon


@tagged('post_install', '-at_install', 'campus_ui')
class TestCampusPmbUiTours(CampusHttpCommon):
    """Comprehensive browser UI tours for PMB admission workflow, views, and website tab."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        internal = cls.env.ref('base.group_user')
        cls.pmb_user = cls.env['res.users'].create({
            'name': '%s PMB UI Officer' % TAG,
            'login': 'zz.ui.pmb@contoh.test',
            'password': cls.PORTAL_PASSWORD,
            'group_ids': [(6, 0, [
                internal.id,
                cls.env.ref('campus_pmb.group_pmb').id,
            ])],
        })
        cls.pmb_hr_user = cls.env['res.users'].create({
            'name': '%s PMB HR UI Officer' % TAG,
            'login': 'zz.ui.pmb.hr@contoh.test',
            'password': cls.PORTAL_PASSWORD,
            'group_ids': [(6, 0, [
                internal.id,
                cls.env.ref('hr.group_hr_user').id,
                cls.env.ref('campus_pmb.group_pmb').id,
            ])],
        })
        cls.pmb_emp = cls.env['hr.employee'].create({
            'name': '%s PMB UI Officer' % TAG,
            'academic_role': 'pmb',
            'user_id': cls.pmb_user.id,
        })
        cls.env['campus.jurisdiction'].create({
            'employee_id': cls.pmb_emp.id,
            'scope': 'pmb',
            'faculty_ids': [(6, 0, [cls.faculty.id])],
            'all_programs': True,
        })
        cls.admission = cls.env['campus.admission'].create({
            'name': '%s Calon PMB UI' % TAG,
            'email': 'zz.calon.pmb.ui@contoh.test',
            'faculty_id': cls.faculty.id,
            'program_id': cls.program.id,
            'academic_year_id': cls.year.id,
        })
        cls.fee_rule = cls.env['campus.admission.fee'].search([], limit=1) or cls.env['campus.admission.fee'].create({
            'fee_type': 'registration',
            'admission_path': 'regular',
            'amount': 250000.0,
        })
        cls.req_rule = cls.env['campus.admission.requirement'].search([], limit=1) or cls.env['campus.admission.requirement'].create({
            'document_type': 'diploma',
            'admission_path': 'all',
        })

    def test_01_pmb_officer_submits_applicant_ui_tour(self):
        self.start_tour(
            '/odoo/campus.admission/%d' % self.admission.id,
            'campus_pmb_applicant_submit_ui_tour',
            login=self.pmb_user.login,
        )
        self.admission.invalidate_recordset(['state'])
        self.assertEqual(self.admission.state, 'submitted')

    def test_02_pmb_officer_accepts_and_registers_applicant_ui_tour(self):
        adm = self.env['campus.admission'].create({
            'name': '%s Calon Register UI' % TAG,
            'email': 'zz.calon.reg.ui@contoh.test',
            'faculty_id': self.faculty.id,
            'program_id': self.program.id,
            'academic_year_id': self.year.id,
        })
        adm.action_submit()
        adm.action_start_document_review()
        adm.document_line_ids.write({'received': True})
        adm.write({
            'registration_fee_paid': True,
            'reregistration_fee_paid': True,
        })
        self.start_tour(
            '/odoo/campus.admission/%d' % adm.id,
            'campus_pmb_accept_and_register_ui_tour',
            login=self.pmb_user.login,
        )
        self.env.invalidate_all()
        self.assertEqual(adm.state, 'registered')
        self.assertTrue(adm.partner_id)

    def test_03_pmb_officer_opens_all_pmb_menus_ui_tour(self):
        adm_action = self.env.ref('campus_pmb.action_campus_admission')
        self.start_tour(
            '/odoo/action-%d' % adm_action.id,
            'campus_pmb_list_or_kanban_to_form_ui_tour',
            login=self.pmb_user.login,
        )
        staff_action = self.env.ref('campus_pmb.action_hr_employee_pmb_staff')
        self.start_tour(
            '/odoo/action-%d' % staff_action.id,
            'campus_pmb_list_or_kanban_to_form_ui_tour',
            login=self.pmb_hr_user.login,
        )
        for xmlid in (
            'campus_pmb.action_campus_admission_fee',
            'campus_pmb.action_campus_admission_requirement',
        ):
            action = self.env.ref(xmlid)
            self.start_tour(
                '/odoo/action-%d' % action.id,
                'campus_pmb_list_only_ui_tour',
                login=self.pmb_user.login,
            )

    def test_04_public_homepage_pmb_tab_ui_tour(self):
        self.start_tour('/', 'campus_pmb_homepage_tab_ui_tour')
