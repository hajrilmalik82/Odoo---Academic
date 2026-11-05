import re

from odoo.tests.common import tagged

from odoo.addons.campus_core.tests.common import TAG, CampusHttpCommon


@tagged('post_install', '-at_install')
class TestPublicAdmissionForm(CampusHttpCommon):
    """The one page anyone on the internet can reach.

    It is the only unauthenticated write path in the whole suite, so what it
    accepts, what it refuses and what it says while refusing all matter. None
    of that is visible from a TransactionCase: the CSRF check, the
    auth="public" decorator and the rendering happen in the request.
    """

    def _form(self):
        response = self.url_open('/admission')
        self.assertEqual(response.status_code, 200)
        return response.text

    def _token(self, html):
        match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
        self.assertTrue(match, "the public form must carry a CSRF token")
        return match.group(1)

    def _submit(self, **overrides):
        html = self._form()
        data = {
            'csrf_token': self._token(html),
            'name': '%s Calon Mahasiswa' % TAG,
            'email': 'zz.calon.http@contoh.test',
            'phone': '081200000001',
            'faculty_id': str(self.faculty.id),
            'program_id': str(self.program.id),
            'admission_path': 'regular',
        }
        data.update(overrides)
        return self.url_open('/admission/submit', data=data, allow_redirects=False)

    def _admission(self, email):
        return self.env['campus.admission'].search([('email', '=', email)], limit=1)

    # --- the page -----------------------------------------------------------

    def test_an_anonymous_visitor_can_open_the_form(self):
        html = self._form()
        self.assertIn('csrf_token', html)
        self.assertIn(self.faculty.name, html)
        self.assertIn('display_registration_fee', html)
        self.assertIn('display_reregistration_fee', html)

    def test_the_thank_you_page_renders(self):
        self.assertEqual(self.url_open('/admission/thanks').status_code, 200)

    # --- a good submission --------------------------------------------------

    def test_a_valid_application_is_created_and_lands_in_draft(self):
        response = self._submit()
        self.assertIn(response.status_code, (302, 303))
        self.assertIn('/admission/thanks', response.headers.get('Location', ''))

        admission = self._admission('zz.calon.http@contoh.test')
        self.assertTrue(admission)
        self.assertEqual(admission.state, 'draft')
        self.assertEqual(admission.program_id, self.program)
        self.assertTrue(admission.document_line_ids, "the checklist arrives with it")

    def test_the_state_cannot_be_chosen_from_the_wire(self):
        """A visitor must not be able to skip submission and document review by
        posting state=accepted and landing in the officer's queue."""
        self._submit(email='zz.lompat.http@contoh.test', state='accepted')
        admission = self._admission('zz.lompat.http@contoh.test')
        self.assertTrue(admission)
        self.assertEqual(admission.state, 'draft')

    # --- what it refuses ----------------------------------------------------

    def test_a_submission_without_a_token_is_refused(self):
        html = self._form()
        response = self.url_open('/admission/submit', data={
            'name': 'X', 'email': 'zz.tanpa.token@contoh.test',
            'program_id': str(self.program.id),
        }, allow_redirects=False)
        self.assertNotEqual(response.status_code, 303)
        self.assertFalse(self._admission('zz.tanpa.token@contoh.test'))

    def test_a_programme_that_does_not_exist_is_refused_politely(self):
        """MissingError would hand an anonymous visitor the model name, the
        record id and the internal uid."""
        response = self._submit(email='zz.palsu.http@contoh.test', program_id='99999999')
        self.assertIn(response.status_code, (302, 303))
        location = response.headers.get('Location', '')
        self.assertIn('error=', location)
        self.assertNotIn('campus.admission', location)
        self.assertNotIn('uid', location)
        self.assertFalse(self._admission('zz.palsu.http@contoh.test'))

    def test_a_programme_from_another_faculty_is_refused(self):
        other = self.env['academic.faculty'].create({
            'name': '%s Fakultas Silang HTTP' % TAG, 'code': 'ZFH',
        })
        response = self._submit(
            email='zz.silang.http@contoh.test', faculty_id=str(other.id),
        )
        self.assertIn('error=', response.headers.get('Location', ''))
        self.assertFalse(self._admission('zz.silang.http@contoh.test'))

    def test_an_invalid_admission_path_is_refused(self):
        response = self._submit(
            email='zz.jalur.http@contoh.test', admission_path='tidak-ada',
        )
        self.assertIn('error=', response.headers.get('Location', ''))
        self.assertFalse(self._admission('zz.jalur.http@contoh.test'))

    def test_applying_twice_is_reported_to_the_applicant(self):
        """Not as a system error: a UNIQUE violation is an IntegrityError and
        used to fall through to the controller's catch-all branch."""
        self._submit(email='zz.ganda.http@contoh.test')
        self.env.flush_all()
        response = self._submit(email='zz.ganda.http@contoh.test')
        location = response.headers.get('Location', '')
        self.assertIn('error=', location)
        self.assertNotIn('system', location.lower())


@tagged('post_install', '-at_install')
class TestPmbMenu(CampusHttpCommon):
    """The Admissions app tile.

    campus_core.menu_academic_root is group-gated for a stated reason: without
    it the tile shows for every internal user, including someone who only has
    Inventory, and clicking through produces an access error instead of simply
    not being there. This root carried no gate at all while campus.admission is
    readable by PMB staff and administrators only.
    """

    def test_the_admissions_tile_is_gated(self):
        menu = self.env.ref('campus_pmb.menu_campus_pmb_root')
        self.assertTrue(menu.group_ids, "the Admissions root menu must be gated")

    def test_it_is_open_to_exactly_who_may_read_an_admission(self):
        groups = self.env.ref('campus_pmb.menu_campus_pmb_root').group_ids
        self.assertIn(self.env.ref('campus_pmb.group_pmb'), groups)
        self.assertIn(self.env.ref('campus_core.group_campus_administrator'), groups)
        self.assertNotIn(self.env.ref('base.group_user'), groups)
