from odoo.tests.common import tagged

from odoo.addons.campus_core.tests.common import CampusHttpCommon


@tagged('post_install', '-at_install', 'campus_ui')
class TestCampusPortalUiTours(CampusHttpCommon):
    """Comprehensive browser UI tours for student KRS & KHS portal flows."""

    def test_01_student_opens_krs_portal_ui_tour(self):
        self._make_krs()
        self.start_tour(
            '/my',
            'campus_portal_student_ui_tour',
            login=self.student_user.login,
        )

    def test_02_student_krs_register_add_remove_and_submit_ui_tour(self):
        self.start_tour(
            '/my/krs',
            'campus_portal_krs_register_add_remove_submit_ui_tour',
            login=self.student_user.login,
            timeout=60,
        )
        krs = self.env['academic.krs'].search([
            ('student_id', '=', self.student.id),
        ], order='id desc', limit=1)
        self.assertTrue(krs)
        self.assertEqual(krs.state, 'submitted')
        self.assertEqual(len(krs.line_ids), 1)

    def test_03_student_opens_khs_and_transcript_portal_ui_tour(self):
        krs = self._make_krs()
        krs.action_submit()
        krs.action_approve()
        krs.action_lock()
        self.start_tour(
            '/my',
            'campus_portal_khs_transcript_ui_tour',
            login=self.student_user.login,
        )

    def test_04_public_homepage_portal_tab_ui_tour(self):
        self.start_tour('/', 'campus_portal_homepage_tab_ui_tour')
