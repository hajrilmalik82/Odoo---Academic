from datetime import timedelta
import re

from odoo import fields
from odoo.tests.common import tagged

from odoo.addons.campus_core.tests.common import TAG, CampusHttpCommon
from .test_thesis_workflow import ThesisFixtureMixin


@tagged('post_install', '-at_install')
class TestThesisPortal(ThesisFixtureMixin, CampusHttpCommon):
    """HTTP route, CSRF, QWeb rendering, file upload, PDF report, and IDOR checks."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_thesis_actors()

    def _csrf_token(self, html):
        match = (
            re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
            or re.search(r'csrf_token:\s*"([^"]+)"', html)
        )
        self.assertTrue(match, "the page must carry a CSRF token")
        return match.group(1)

    def test_counters_answer_for_student_and_outsider(self):
        self.sign_in_as_outsider()
        res = self.opener.post(
            self.base_url() + '/my/counters',
            json={'params': {'counters': ['thesis_count']}},
        ).json()
        self.assertEqual(res['result'], {'thesis_count': 0})

        self._record_metopen_grade(self.student, score=85.0)
        self._make_thesis()
        self.sign_in_as_student()
        res = self.opener.post(
            self.base_url() + '/my/counters',
            json={'params': {'counters': ['thesis_count']}},
        ).json()
        self.assertEqual(res['result'], {'thesis_count': 1})

    def test_portal_blocks_ineligible_student_registration(self):
        self.sign_in_as_student()
        page = self.url_open('/my/thesis')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Research Methodology', page.text)
        self.assertNotIn('/my/thesis/create', page.text)

        # Direct POST bypassing the hidden form still refuses creation
        csrf = self._csrf_token(self.url_open('/my/home').text)
        resp = self.url_open('/my/thesis/create', data={
            'csrf_token': csrf,
            'title': 'Bypass Attempt',
            'supervisor_id': self.supervisor_emp.id,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(self.env['campus.thesis'].search([('student_id', '=', self.student.id)]))

    def test_full_portal_to_graduation_journey(self):
        today = fields.Date.context_today(self.env.user)
        grad = self.env['campus.graduation.schedule'].create({
            'name': '%s Wisuda Portal 2026' % TAG,
            'graduation_date': today + timedelta(days=45),
            'registration_deadline': today + timedelta(days=30),
            'location': 'Balairung Utama',
        })
        self._record_metopen_grade(self.student, score=88.0)

        self.sign_in_as_student()
        list_resp = self.url_open('/my/thesis')
        self.assertEqual(list_resp.status_code, 200)
        csrf = self._csrf_token(list_resp.text)

        # 1. Create thesis draft from portal
        create_resp = self.url_open('/my/thesis/create', data={
            'csrf_token': csrf,
            'title': '%s Judul Skripsi Awal' % TAG,
            'research_topic': 'Riset sistem terdistribusi.',
            'supervisor_id': self.supervisor_emp.id,
            'co_supervisor_id': '',
        })
        self.assertEqual(create_resp.status_code, 200)
        thesis = self.env['campus.thesis'].search([('student_id', '=', self.student.id)], limit=1)
        self.assertTrue(thesis)
        self.assertEqual(thesis.state, 'draft')

        # 2. Update title & submit for supervisor approval
        detail_resp = self.url_open('/my/thesis/%s' % thesis.id)
        csrf = self._csrf_token(detail_resp.text)
        self.url_open('/my/thesis/%s/update' % thesis.id, data={
            'csrf_token': csrf,
            'title': '%s Judul Skripsi Revisi' % TAG,
            'research_topic': 'Riset arsitektur ERP.',
            'supervisor_id': self.supervisor_emp.id,
            'co_supervisor_id': '',
        })
        self.assertEqual(thesis.title, '%s Judul Skripsi Revisi' % TAG)

        self.url_open('/my/thesis/%s/submit' % thesis.id, data={'csrf_token': csrf})
        self.assertEqual(thesis.state, 'supervisor_approval')

        # 3. Supervisor approves -> proposal stage; student logs progress with attachment
        thesis.with_user(self.supervisor_user).action_supervisor_approve()
        self.assertEqual(thesis.state, 'proposal')

        detail_resp = self.url_open('/my/thesis/%s' % thesis.id)
        csrf = self._csrf_token(detail_resp.text)
        self.url_open(
            '/my/thesis/%s/add_progress' % thesis.id,
            data={
                'csrf_token': csrf,
                'milestone': 'Bab I - III Proposal',
                'description': 'Draft proposal lengkap.',
                'progress_percent': '80',
            },
            files={'attachment': ('proposal.pdf', b'%PDF-1.4 proposal', 'application/pdf')},
        )
        self.assertEqual(len(thesis.progress_line_ids), 1)
        thesis.progress_line_ids.with_user(self.supervisor_user).action_approve()
        self.assertEqual(thesis.proposal_progress, 80.0)

        # 4. Supervisor approves proposal -> waiting MK Skripsi in KRS
        thesis.with_user(self.supervisor_user).action_approve_proposal()
        self.assertEqual(thesis.state, 'proposal_approved')

        # Enroll & approve MK Skripsi, then click Start Thesis from portal
        self._enroll_thesis_krs(self.student, approve=True)
        detail_resp = self.url_open('/my/thesis/%s' % thesis.id)
        csrf = self._csrf_token(detail_resp.text)
        self.url_open('/my/thesis/%s/start_thesis' % thesis.id, data={'csrf_token': csrf})
        self.assertEqual(thesis.state, 'thesis')

        # 5. Log thesis progress & supervisor approves thesis -> Yudisium filing
        detail_resp = self.url_open('/my/thesis/%s' % thesis.id)
        csrf = self._csrf_token(detail_resp.text)
        self.url_open('/my/thesis/%s/add_progress' % thesis.id, data={
            'csrf_token': csrf,
            'milestone': 'Bab IV - V & Sidang',
            'description': 'Naskah skripsi final siap yudisium.',
            'progress_percent': '100',
        })
        thesis.with_user(self.supervisor_user).action_approve_thesis()
        self.assertEqual(thesis.state, 'yudisium_docs')

        # 6. Upload Yudisium documents from portal, staff verifies, submit Yudisium
        detail_resp = self.url_open('/my/thesis/%s' % thesis.id)
        csrf = self._csrf_token(detail_resp.text)
        first_doc = thesis.yudisium_document_ids[:1]
        self.url_open(
            '/my/thesis/%s/upload_document/%s' % (thesis.id, first_doc.id),
            data={'csrf_token': csrf},
            files={'attachment': ('naskah.pdf', b'%PDF-1.4 final', 'application/pdf')},
        )
        self.assertTrue(first_doc.submitted_by_student)
        thesis.yudisium_document_ids.write({'received': True})

        self.url_open('/my/thesis/%s/submit_yudisium' % thesis.id, data={'csrf_token': csrf})
        self.assertEqual(thesis.state, 'yudisium_supervisor')

        # 7. Sequential Yudisium approvals -> Nearest Graduation assigned & visible in portal
        thesis.with_user(self.supervisor_user).action_yudisium_approve_supervisor()
        thesis.with_user(self.advisor_user).action_yudisium_approve_advisor()
        thesis.with_user(self.dean_user).action_yudisium_approve_dean()
        self.assertEqual(thesis.state, 'graduated')
        self.assertEqual(thesis.graduation_id, grad)

        final_page = self.url_open('/my/thesis/%s' % thesis.id)
        self.assertEqual(final_page.status_code, 200)
        self.assertIn(grad.name, final_page.text)

        # 8. PDF report download works for own student
        pdf_resp = self.url_open('/my/thesis/%s/report?download=1' % thesis.id)
        self.assertEqual(pdf_resp.status_code, 200)
        self.assertIn('application/pdf', pdf_resp.headers.get('Content-Type', ''))

    def test_horizontal_isolation_blocks_outsider(self):
        self._record_metopen_grade(self.student, score=85.0)
        thesis = self._make_thesis()
        self.sign_in_as_outsider()

        resp = self.url_open('/my/thesis/%s' % thesis.id)
        self.assertNotIn(thesis.title, resp.text)

        csrf = self._csrf_token(self.url_open('/my/home').text)
        self.url_open('/my/thesis/%s/submit' % thesis.id, data={'csrf_token': csrf})
        self.assertEqual(thesis.state, 'draft')

        pdf_resp = self.url_open('/my/thesis/%s/report' % thesis.id)
        self.assertNotIn('application/pdf', pdf_resp.headers.get('Content-Type', ''))

    def test_website_homepage_renders_thesis_docs_tab(self):
        resp = self.url_open('/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Campus Thesis', resp.text)

    def test_portal_upload_validation_reupload_resets_received_and_cancelled_reset_blocked(self):
        self._record_metopen_grade(self.student, score=88.0)
        self._enroll_thesis_krs(self.student, approve=True)
        thesis = self._make_thesis()
        thesis.action_submit_supervisor()
        thesis.with_user(self.supervisor_user).action_supervisor_approve()

        self.sign_in_as_student()
        csrf = self._csrf_token(self.url_open('/my/thesis/%s' % thesis.id).text)

        # Reject .html / .svg / spoofed .pdf / polyglot .pdf / fake ZIP .docx uploads
        for bad_name, bad_bytes, bad_mime in (
            ('xss.html', b'<html><script>alert(1)</script></html>', 'text/html'),
            ('spoof.pdf', b'<script>alert(1)</script>', 'application/pdf'),
            ('polyglot.pdf', b'<!-- %PDF-1.4 --><html><script>alert(1)</script></html>', 'application/pdf'),
            ('fake.docx', b'PK\x03\x04not-a-real-docx-archive', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
        ):
            self.url_open(
                '/my/thesis/%s/add_progress' % thesis.id,
                data={
                    'csrf_token': csrf,
                    'milestone': 'Bad Upload',
                    'description': 'Should fail',
                    'progress_percent': '10',
                },
                files={'attachment': (bad_name, bad_bytes, bad_mime)},
            )
            self.assertFalse(thesis.progress_line_ids)

        # Untrusted ?error= / ?success= query params must not render portal alerts
        spoof_html = self.url_open('/my/thesis?error=Fake+Phish&success=Fake+Win').text
        self.assertNotIn('Fake Phish', spoof_html)
        self.assertNotIn('Fake Win', spoof_html)

        # Windows fakepath is stripped cleanly on valid PDF
        self.url_open(
            '/my/thesis/%s/add_progress' % thesis.id,
            data={
                'csrf_token': csrf,
                'milestone': 'Win Path',
                'description': 'Valid PDF',
                'progress_percent': '25',
            },
            files={'attachment': (r'C:\fakepath\bab1.pdf', b'%PDF-1.4 valid', 'application/pdf')},
        )
        self.assertEqual(thesis.progress_line_ids[:1].attachment_filename, 'bab1.pdf')

        # Advance to yudisium_docs, verify doc, then re-upload -> received must reset to False
        thesis.with_user(self.supervisor_user).action_approve_proposal()
        thesis.with_user(self.supervisor_user).action_approve_thesis()
        doc = thesis.yudisium_document_ids[:1]
        thesis.yudisium_document_ids.write({'received': True})
        self.assertTrue(thesis.documents_complete)

        csrf = self._csrf_token(self.url_open('/my/thesis/%s' % thesis.id).text)
        self.url_open(
            '/my/thesis/%s/upload_document/%s' % (thesis.id, doc.id),
            data={'csrf_token': csrf},
            files={'attachment': ('revised.pdf', b'%PDF-1.4 revised', 'application/pdf')},
        )
        doc.invalidate_recordset()
        thesis.invalidate_recordset()
        self.assertFalse(doc.received)
        self.assertFalse(thesis.documents_complete)

        # Staff cancels thesis -> portal student cannot reset_draft back to draft
        thesis.action_cancel()
        self.url_open('/my/thesis/%s/reset_draft' % thesis.id, data={'csrf_token': csrf})
        thesis.invalidate_recordset()
        self.assertEqual(thesis.state, 'cancelled')
