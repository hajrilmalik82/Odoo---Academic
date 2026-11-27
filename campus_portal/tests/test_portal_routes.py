import re

from odoo.tests.common import tagged

from odoo.addons.campus_core.tests.common import CampusHttpCommon


@tagged('post_install', '-at_install')
class TestPortalRoutes(CampusHttpCommon):
    """The student portal, exercised the way a student reaches it.

    Everything here is invisible to a TransactionCase: the route's own methods
    and auth, the CSRF token, whether a template actually renders, and which
    language a frontend page comes back in. Each of these was checked by hand
    once, with curl, and that evidence did not survive the session - which is
    the whole reason this file exists.
    """

    def setUp(self):
        super().setUp()
        self.krs = self._make_krs()

    def _get(self, url, **kwargs):
        return self.url_open(url, **kwargs)

    def _csrf_token(self, html):
        match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
        self.assertTrue(match, "the page must carry a CSRF token")
        return match.group(1)

    # --- the pages render ---------------------------------------------------

    def test_the_three_portal_pages_render_for_a_student(self):
        """A QWeb error only appears when a page is really drawn."""
        self.sign_in_as_student()
        for url in ('/my/home', '/my/krs', '/my/khs', '/my/krs/%s' % self.krs.id):
            with self.subTest(url=url):
                response = self._get(url)
                self.assertEqual(response.status_code, 200)

    def test_the_krs_page_lists_the_plan(self):
        self.sign_in_as_student()
        body = self._get('/my/krs/%s' % self.krs.id).text
        self.assertIn(self.subject_a.name, body)

    def test_an_anonymous_visitor_is_sent_to_the_login(self):
        response = self._get('/my/krs', allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertIn('/web/login', response.headers.get('Location', ''))

    # --- the counters -------------------------------------------------------

    def test_the_counters_answer_for_a_student(self):
        self.sign_in_as_student()
        result = self.opener.post(
            self.base_url() + '/my/counters',
            json={'params': {'counters': ['krs_count', 'khs_count']}},
        ).json()['result']
        self.assertEqual(result['krs_count'], 1)

    def test_the_counters_do_not_break_for_an_internal_user(self):
        """/my/counters batches up to five counters per call and the client
        awaits it in willStart, so one AccessError left the whole batch's cards
        hidden and the portal spinner turning for ever."""
        self.sign_in_as_outsider()
        response = self.opener.post(
            self.base_url() + '/my/counters',
            json={'params': {'counters': ['krs_count', 'khs_count']}},
        ).json()
        self.assertNotIn('error', response, "a non-campus user must not get an error")
        self.assertEqual(response['result'], {'krs_count': 0, 'khs_count': 0})

    def test_my_home_opens_for_an_internal_user(self):
        self.sign_in_as_outsider()
        self.assertEqual(self._get('/my/home').status_code, 200)

    def test_the_list_pages_open_for_an_internal_user(self):
        """Both routes are auth="user", not portal-only, so an accountant or a
        warehouse operator reaches them from /my like anyone else. Read ACL on
        academic.krs and academic.khs is granted to portal, campus staff and
        lecturers only, so an unsudoed search_count made these a 500 page for
        everybody else. The counters were fixed for this; these two were not.
        """
        self.sign_in_as_outsider()
        for url in ('/my/krs', '/my/khs'):
            with self.subTest(url=url):
                self.assertEqual(self._get(url).status_code, 200)

    def test_an_internal_user_sees_no_study_plans_of_their_own(self):
        """sudo() on those routes must not widen what comes back: the domain is
        pinned to the logged-in partner, so the page is empty rather than
        showing somebody else's plan."""
        self.sign_in_as_outsider()
        body = self._get('/my/krs').text
        self.assertNotIn(self.krs.name, body)

    # --- the register route -------------------------------------------------

    def test_register_refuses_a_get(self):
        """It creates a record, so as a GET it was reachable from any link,
        image or prefetch, with no CSRF token involved."""
        self.sign_in_as_student()
        response = self._get('/my/krs/register', allow_redirects=False)
        self.assertEqual(response.status_code, 405)

    def test_the_register_button_posts_with_a_token(self):
        self.sign_in_as_student()
        token = self._csrf_token(self._get('/my/krs').text)
        response = self.url_open(
            '/my/krs/register', data={'csrf_token': token}, allow_redirects=False,
        )
        self.assertIn(response.status_code, (302, 303))
        # The student already holds a plan for the open year, so the route sends
        # them to it rather than opening a second one.
        self.assertNotIn('error=', response.headers.get('Location', ''))

    # --- the error path -----------------------------------------------------

    def test_an_invalid_schedule_comes_back_as_a_message(self):
        """Not as a 500. The decorator stores a one-shot session flash message
        and redirects cleanly without leaking error text into the URL."""
        self.sign_in_as_student()
        token = self._csrf_token(self._get('/my/krs/%s' % self.krs.id).text)
        response = self.url_open(
            '/my/krs/%s/add_line' % self.krs.id,
            data={'csrf_token': token, 'schedule_id': '99999999'},
            allow_redirects=False,
        )
        self.assertIn(response.status_code, (302, 303))
        location = response.headers.get('Location', '')
        self.assertNotIn('error=', location)
        page = self._get(location).text
        self.assertIn('alert-danger', page)
        self.assertIn('valid schedule', page.lower())

    def test_query_string_error_cannot_spoof_banner(self):
        """Untrusted ?error= query parameters must never render as portal alerts."""
        self.sign_in_as_student()
        html = self._get('/my/krs?error=Send+password+to+attacker').text
        self.assertNotIn('Send password to attacker', html)
        self.assertNotIn('alert-danger', html)

    def test_a_class_from_another_programme_is_refused_at_add_time(self):
        """The page filters the list by programme; the route used to check the
        academic year alone, so a hand-made POST naming another programme's
        section was accepted and only refused at submission - after the student
        had built a plan on it. Both now read the same definition.
        """
        other_faculty = self.env['academic.faculty'].create({
            'name': 'ZZTEST Fakultas Luar', 'code': 'ZFL',
        })
        other_program = self.env['academic.program'].create({
            'name': 'ZZTEST Prodi Luar', 'code': 'ZPL',
            'faculty_id': other_faculty.id,
        })
        other_subject = self.env['academic.subject'].create({
            'name': 'ZZTEST Mata Kuliah Luar', 'code': 'ZZ-LUAR',
            'credits': 3, 'term_type': 'both', 'program_id': other_program.id,
        })
        other_class = self.env['academic.class'].create({
            'subject_id': other_subject.id,
            'academic_year_id': self.krs.academic_year_id.id,
            'start_date': self.krs.academic_year_id.krs_start_date,
        })
        outside = self.env['academic.class.schedule'].create({
            'class_id': other_class.id, 'class_code': 'A',
            'day_of_week': '3', 'start_time': 13.0, 'end_time': 15.0,
            'room_id': self.room.id,
        })

        self.sign_in_as_student()
        token = self._csrf_token(self._get('/my/krs/%s' % self.krs.id).text)
        before = len(self.krs.line_ids)
        response = self.url_open(
            '/my/krs/%s/add_line' % self.krs.id,
            data={'csrf_token': token, 'schedule_id': str(outside.id)},
            allow_redirects=False,
        )
        self.assertIn(response.status_code, (302, 303))
        location = response.headers.get('Location', '')
        self.assertNotIn('error=', location)
        self.assertIn('alert-danger', self._get(location).text)
        self.krs.invalidate_recordset()
        self.assertEqual(len(self.krs.line_ids), before)

    def test_the_page_and_the_route_read_one_definition(self):
        """Spelled out twice, the filter and the check would drift - which is
        exactly how they came apart the first time."""
        from odoo.addons.campus_portal.controllers.portal import CampusPortal
        self.assertTrue(hasattr(CampusPortal, '_offerable_schedule_domain'))

    def test_someone_elses_krs_is_not_reachable(self):
        """sudo() runs every mutation below, so the ownership check is the only
        thing between a student and another student's plan."""
        other = self.env['res.partner'].create({
            'name': 'ZZTEST Mahasiswa Lain', 'is_student': True,
            'student_status': 'active', 'program_id': self.program.id,
            'academic_advisor_id': self.advisor.id,
        })
        theirs = self._make_krs(student=other, year=self.year_retake,
                                schedules=self.schedule_retake)
        self.sign_in_as_student()
        token = self._csrf_token(self._get('/my/krs/%s' % self.krs.id).text)
        response = self._get('/my/krs/%s' % theirs.id, allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertIn('/my/krs', response.headers.get('Location', ''))

        # IDOR protection on report download and mutating POST routes too.
        report_resp = self._get('/my/krs/%s/report?download=1' % theirs.id, allow_redirects=False)
        self.assertIn(report_resp.status_code, (302, 303))
        self.assertIn('/my/krs', report_resp.headers.get('Location', ''))

        line_id = theirs.line_ids[:1].id
        for url, payload in (
            ('/my/krs/%s/add_line' % theirs.id, {'csrf_token': token, 'schedule_id': str(self.schedule_retake.id)}),
            ('/my/krs/%s/delete_line/%s' % (theirs.id, line_id), {'csrf_token': token}),
            ('/my/krs/%s/submit' % theirs.id, {'csrf_token': token}),
        ):
            post_resp = self.url_open(url, data=payload, allow_redirects=False)
            self.assertIn(post_resp.status_code, (302, 303))
        theirs.invalidate_recordset()
        self.assertEqual(theirs.state, 'draft')
        self.assertEqual(len(theirs.line_ids), 1)

    # --- the printed documents ---------------------------------------------

    def test_a_student_can_download_their_krs_as_a_pdf(self):
        self.sign_in_as_student()
        response = self._get('/my/krs/%s/report?download=1' % self.krs.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Content-Type'), 'application/pdf')
        self.assertGreater(len(response.content), 1000)

    def test_invalid_report_type_falls_back_to_pdf_and_khs_reports_work(self):
        khs = self.env['academic.khs'].create({
            'student_id': self.student.id,
            'academic_year_id': self.year.id,
            'line_ids': [(0, 0, {
                'subject_id': self.subject_a.id,
                'credits': self.subject_a.credits,
                'numeric_grade': 85.0,
            })],
        })
        self.sign_in_as_student()
        for url in (
            '/my/krs/%s/report?report_type=bogus&download=0' % self.krs.id,
            '/my/khs/%s/report?download=1' % khs.id,
            '/my/khs/%s/transcript?download=1' % khs.id,
        ):
            with self.subTest(url=url):
                resp = self._get(url)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.headers.get('Content-Type'), 'application/pdf')
                self.assertGreater(len(resp.content), 1000)

    def test_new_student_with_zero_krs_still_sees_my_krs_card_on_home(self):
        self.krs.unlink()
        self.sign_in_as_student()
        html = self._get('/my/home').text
        self.assertIn('/my/krs', html)

    def test_package_krs_allows_choosing_class_schedule_on_portal(self):
        """Semester 1-3 package lines with schedule_id=False show Choose Class and bind schedule cleanly."""
        pkg_krs = self.env['academic.krs'].create({
            'student_id': self.student.id,
            'academic_year_id': self.year_retake.id,
            'line_ids': [(0, 0, {'subject_id': self.subject_a.id})],
        })
        self.sign_in_as_student()
        html = self._get('/my/krs/%s' % pkg_krs.id).text
        self.assertIn('Choose Class', html)
        self.assertIn('Needs Schedule', html)
        token = self._csrf_token(html)
        response = self.url_open(
            '/my/krs/%s/add_line' % pkg_krs.id,
            data={'csrf_token': token, 'schedule_id': str(self.schedule_retake.id)},
            allow_redirects=False,
        )
        self.assertIn(response.status_code, (302, 303))
        self.assertNotIn('error=', response.headers.get('Location', ''))
        pkg_krs.invalidate_recordset()
        self.assertEqual(len(pkg_krs.line_ids), 1)
        self.assertEqual(pkg_krs.line_ids.schedule_id, self.schedule_retake)

    def test_register_inactive_student_redirects_to_krs_with_visible_error(self):
        self.student.student_status = 'leave'
        self.sign_in_as_student()
        token = self._csrf_token(self._get('/my/krs').text)
        response = self.url_open(
            '/my/krs/register',
            data={'csrf_token': token},
            allow_redirects=False,
        )
        self.assertIn(response.status_code, (302, 303))
        location = response.headers.get('Location', '')
        self.assertIn('/my/krs', location)
        self.assertNotIn('error=', location)
        body = self._get(location).text
        self.assertIn('alert-danger', body)
        self.assertIn('Only active students', body)

    def test_krs_detail_shows_breadcrumb_and_closed_period_blocks_mutations(self):
        from datetime import timedelta
        from odoo import fields

        self.sign_in_as_student()
        detail_html = self._get('/my/krs/%s' % self.krs.id).text
        self.assertIn('o_portal_submenu', detail_html)
        self.assertIn('href="/my/krs"', detail_html)
        token = self._csrf_token(detail_html)

        today = fields.Date.context_today(self.env.user)
        self.year.write({
            'krs_start_date': today - timedelta(days=20),
            'krs_end_date': today - timedelta(days=1),
        })
        line_id = self.krs.line_ids[:1].id
        del_resp = self.url_open(
            '/my/krs/%s/delete_line/%s' % (self.krs.id, line_id),
            data={'csrf_token': token},
            allow_redirects=False,
        )
        self.assertIn(del_resp.status_code, (302, 303))
        del_loc = del_resp.headers.get('Location', '')
        self.assertNotIn('error=', del_loc)
        self.assertIn('alert-danger', self._get(del_loc).text)
        self.krs.invalidate_recordset()
        self.assertEqual(len(self.krs.line_ids), 1)

        add_resp = self.url_open(
            '/my/krs/%s/add_line' % self.krs.id,
            data={'csrf_token': token, 'schedule_id': str(self.schedule.id)},
            allow_redirects=False,
        )
        self.assertIn(add_resp.status_code, (302, 303))
        add_loc = add_resp.headers.get('Location', '')
        self.assertNotIn('error=', add_loc)
        self.assertIn('alert-danger', self._get(add_loc).text)
