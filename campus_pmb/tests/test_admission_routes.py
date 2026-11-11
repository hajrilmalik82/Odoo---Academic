import json

from odoo.tests.common import tagged

from odoo.addons.campus_core.tests.common import TAG, CampusHttpCommon


@tagged('post_install', '-at_install')
class TestPublicAdmissionApi(CampusHttpCommon):
    """The public JSON API endpoints consumed by the standalone frontend-app."""

    def _get_options(self):
        response = self.url_open('/api/admission/options')
        self.assertEqual(response.status_code, 200)
        return json.loads(response.text)

    def _submit(self, **overrides):
        payload = {
            'fullName': '%s Calon Mahasiswa' % TAG,
            'email': 'zz.calon.http@contoh.test',
            'phoneNumber': '081200000001',
            'schoolOrigin': 'SMA Negeri 1',
            'facultyId': str(self.faculty.id),
            'studyProgramId': str(self.program.id),
            'admissionTrackId': 'regular',
        }
        payload.update(overrides)
        return self.url_open(
            '/api/admission/submit',
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
        )

    def _admission(self, email):
        return self.env['campus.admission'].search([('email', '=', email)], limit=1)

    # --- GET /api/admission/options -----------------------------------------

    def test_options_endpoint_returns_faculties_programs_tracks_and_fees(self):
        body = self._get_options()
        self.assertEqual(body.get('status'), 'success')
        data = body['data']
        faculty_ids = [f['id'] for f in data['faculties']]
        program_ids = [p['id'] for p in data['studyPrograms']]
        track_ids = [t['id'] for t in data['admissionTracks']]
        self.assertIn(str(self.faculty.id), faculty_ids)
        self.assertIn(str(self.program.id), program_ids)
        self.assertIn('regular', track_ids)
        self.assertIn('scholarship', track_ids)
        self.assertIn('transfer', track_ids)
        self.assertIn('regular', data['feeMatrix'])

    # --- POST /api/admission/submit -----------------------------------------

    def test_a_valid_application_is_created_and_lands_in_draft(self):
        response = self._submit()
        self.assertEqual(response.status_code, 201)
        body = json.loads(response.text)
        self.assertEqual(body.get('status'), 'success')
        self.assertTrue(body['data']['registrationNumber'].startswith('PMB/'))

        admission = self._admission('zz.calon.http@contoh.test')
        self.assertTrue(admission)
        self.assertEqual(admission.state, 'draft')
        self.assertEqual(admission.program_id, self.program)
        self.assertTrue(admission.document_line_ids, "the checklist arrives with it")

    def test_the_state_cannot_be_chosen_from_the_wire(self):
        """A visitor must not be able to skip submission and document review by
        posting state=accepted and landing in the officer's queue."""
        response = self._submit(email='zz.lompat.http@contoh.test', state='accepted')
        self.assertEqual(response.status_code, 201)
        admission = self._admission('zz.lompat.http@contoh.test')
        self.assertTrue(admission)
        self.assertEqual(admission.state, 'draft')

    # --- what it refuses ----------------------------------------------------

    def test_a_programme_that_does_not_exist_is_refused_politely(self):
        """MissingError would hand an anonymous visitor the model name, the
        record id and the internal uid."""
        response = self._submit(email='zz.palsu.http@contoh.test', studyProgramId='99999999')
        self.assertEqual(response.status_code, 400)
        body = json.loads(response.text)
        self.assertEqual(body.get('status'), 'error')
        self.assertNotIn('campus.admission', body.get('message', ''))
        self.assertNotIn('uid', body.get('message', ''))
        self.assertFalse(self._admission('zz.palsu.http@contoh.test'))

    def test_a_programme_from_another_faculty_is_refused(self):
        other = self.env['academic.faculty'].create({
            'name': '%s Fakultas Silang HTTP' % TAG, 'code': 'ZFH',
        })
        response = self._submit(
            email='zz.silang.http@contoh.test', facultyId=str(other.id),
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self._admission('zz.silang.http@contoh.test'))

    def test_an_invalid_admission_path_is_refused(self):
        response = self._submit(
            email='zz.jalur.http@contoh.test', admissionTrackId='tidak-ada',
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self._admission('zz.jalur.http@contoh.test'))

    def test_applying_twice_is_reported_to_the_applicant(self):
        """Not as a system error: a UNIQUE violation is an IntegrityError and
        used to fall through to the controller's catch-all branch."""
        self._submit(email='zz.ganda.http@contoh.test')
        self.env.flush_all()
        response = self._submit(email='zz.ganda.http@contoh.test')
        self.assertEqual(response.status_code, 400)
        body = json.loads(response.text)
        self.assertEqual(body.get('status'), 'error')
        self.assertNotIn('system', body.get('message', '').lower())


@tagged('post_install', '-at_install')
class TestPmbMenu(CampusHttpCommon):
    """The Admissions app tile."""

    def test_the_admissions_tile_is_gated(self):
        menu = self.env.ref('campus_pmb.menu_campus_pmb_root')
        self.assertTrue(menu.group_ids, "the Admissions root menu must be gated")

    def test_it_is_open_to_exactly_who_may_read_an_admission(self):
        groups = self.env.ref('campus_pmb.menu_campus_pmb_root').group_ids
        self.assertIn(self.env.ref('campus_pmb.group_pmb'), groups)
        self.assertIn(self.env.ref('campus_core.group_campus_administrator'), groups)
        self.assertNotIn(self.env.ref('base.group_user'), groups)
