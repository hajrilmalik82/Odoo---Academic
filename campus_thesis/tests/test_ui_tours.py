from datetime import timedelta

from odoo import fields
from odoo.tests.common import tagged

from odoo.addons.campus_core.tests.common import TAG, CampusHttpCommon
from .test_thesis_workflow import ThesisFixtureMixin


@tagged('post_install', '-at_install', 'campus_ui')
class TestCampusThesisUiTours(ThesisFixtureMixin, CampusHttpCommon):
    """Comprehensive browser UI tours for campus_thesis portal, backend views, and website tab."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_thesis_actors()
        internal = cls.env.ref('base.group_user')
        cls.admin_user = cls.env['res.users'].create({
            'name': '%s Admin Thesis UI' % TAG,
            'login': 'zz.ui.admin.thesis@contoh.test',
            'password': cls.PORTAL_PASSWORD,
            'group_ids': [(6, 0, [
                internal.id,
                cls.env.ref('campus_core.group_campus_administrator').id,
            ])],
        })
        today = fields.Date.context_today(cls.env.user)
        cls.grad_schedule = cls.env['campus.graduation.schedule'].search([], limit=1) or cls.env['campus.graduation.schedule'].create({
            'name': '%s Wisuda UI 2026' % TAG,
            'graduation_date': today + timedelta(days=60),
        })
        first_doc_type = cls.env['campus.thesis.document']._document_type_selection()[0][0]
        cls.thesis_req = cls.env['campus.thesis.requirement'].search([], limit=1) or cls.env['campus.thesis.requirement'].create({
            'document_type': first_doc_type,
        })

    def test_01_student_opens_thesis_portal_ui_tour(self):
        self.start_tour(
            '/my/thesis',
            'campus_thesis_portal_ui_tour',
            login=self.student_user.login,
        )

    def test_02_student_creates_updates_and_submits_thesis_portal_ui_tour(self):
        self._record_metopen_grade(self.student, score=85.0)
        self.start_tour(
            '/my/thesis',
            'campus_thesis_create_update_submit_ui_tour',
            login=self.student_user.login,
        )
        thesis = self.env['campus.thesis'].search([('student_id', '=', self.student.id)], limit=1)
        self.assertTrue(thesis)
        self.assertEqual(thesis.title, 'ZZTEST Implementasi Sistem Akademik UI v2')
        self.assertNotEqual(thesis.state, 'draft')

    def test_03_student_adds_thesis_progress_log_portal_ui_tour(self):
        self._record_metopen_grade(self.student, score=85.0)
        self._enroll_thesis_krs(self.student, approve=True)
        thesis = self._make_thesis()
        thesis.action_submit_supervisor()
        thesis.with_user(self.supervisor_user).action_supervisor_approve()
        thesis.action_approve_proposal()
        self.start_tour(
            '/my/thesis/%d' % thesis.id,
            'campus_thesis_progress_log_ui_tour',
            login=self.student_user.login,
        )
        self.env.invalidate_all()
        self.assertEqual(len(thesis.progress_line_ids), 1)
        self.assertEqual(thesis.progress_line_ids[0].milestone, 'Chapter 1 - Introduction')

    def test_04_admin_opens_all_thesis_backend_views_ui_tour(self):
        self._record_metopen_grade(self.student, score=85.0)
        self._make_thesis()
        for xmlid in (
            'campus_thesis.action_campus_thesis',
            'campus_thesis.action_campus_graduation_schedule',
        ):
            action = self.env.ref(xmlid)
            self.start_tour(
                '/odoo/action-%d' % action.id,
                'campus_thesis_list_to_form_ui_tour',
                login=self.admin_user.login,
            )
        req_action = self.env.ref('campus_thesis.action_campus_thesis_requirement')
        self.start_tour(
            '/odoo/action-%d' % req_action.id,
            'campus_thesis_list_only_ui_tour',
            login=self.admin_user.login,
        )

    def test_05_public_homepage_thesis_tab_ui_tour(self):
        self.start_tour('/', 'campus_thesis_homepage_tab_ui_tour')
