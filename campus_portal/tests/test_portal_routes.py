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
        """Not as a 500. The decorator turns the rule into a redirect the
        student can read."""
        self.sign_in_as_student()
        token = self._csrf_token(self._get('/my/krs/%s' % self.krs.id).text)
        response = self.url_open(
            '/my/krs/%s/add_line' % self.krs.id,
            data={'csrf_token': token, 'schedule_id': '99999999'},
            allow_redirects=False,
        )
        self.assertIn(response.status_code, (302, 303))
        self.assertIn('error=', response.headers.get('Location', ''))

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
        response = self._get('/my/krs/%s' % theirs.id, allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertIn('/my/krs', response.headers.get('Location', ''))

    # --- the printed documents ---------------------------------------------

    def test_a_student_can_download_their_krs_as_a_pdf(self):
        self.sign_in_as_student()
        response = self._get('/my/krs/%s/report?download=1' % self.krs.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Content-Type'), 'application/pdf')
        self.assertGreater(len(response.content), 1000)
