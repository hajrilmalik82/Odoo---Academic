from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import tagged

from odoo.addons.campus_core.tests.common import TAG, CampusCommon


@tagged('post_install', '-at_install')
class TestAdmission(CampusCommon):
    """The admission state machine, and what registering an applicant creates.

    The buttons always enforced their own order, but nothing enforced it on a
    plain write - so a list-view inline edit could set Registered and skip the
    step that actually creates the student.
    """

    def _applicant(self, email='zz.pendaftar@contoh.test', **extra):
        vals = {
            'name': '%s Pendaftar' % TAG,
            'email': email,
            'faculty_id': self.faculty.id,
            'program_id': self.program.id,
            'academic_year_id': self.year.id,
        }
        vals.update(extra)
        return self.env['campus.admission'].create(vals)

    def _register(self, admission):
        admission.action_submit()
        admission.action_start_document_review()
        admission.document_line_ids.write({'received': True})
        admission.action_accept()
        admission.action_register()
        return admission

    # --- the graph ---------------------------------------------------------

    def test_a_direct_write_cannot_skip_to_registered(self):
        admission = self._applicant()
        with self.assertRaises(ValidationError):
            admission.write({'state': 'registered'})

    def test_a_direct_write_cannot_skip_document_review(self):
        admission = self._applicant()
        with self.assertRaises(ValidationError):
            admission.write({'state': 'accepted'})

    def test_a_record_cannot_be_created_past_draft(self):
        with self.assertRaises(ValidationError):
            self._applicant(email='zz.lompat@contoh.test', state='accepted')

    def test_a_registered_application_cannot_go_back(self):
        admission = self._register(self._applicant())
        with self.assertRaises(ValidationError):
            admission.write({'state': 'draft'})

    def test_the_sudo_path_is_held_to_the_same_graph(self):
        """Data integrity, not permission: it holds for sudo and admins too."""
        admission = self._applicant()
        with self.assertRaises(ValidationError):
            admission.sudo().write({'state': 'registered'})

    def test_every_transition_goes_through_the_shared_check(self):
        admission = self._applicant()
        admission.action_submit()
        with self.assertRaises(UserError):
            admission.action_submit()

    # --- what registering produces ----------------------------------------

    def test_registering_creates_the_student_and_the_portal_account(self):
        admission = self._register(self._applicant())
        self.assertEqual(admission.state, 'registered')
        self.assertTrue(admission.partner_id.nim)
        self.assertTrue(admission.partner_id.is_student)
        self.assertEqual(admission.user_id.login, admission.email)

    def test_the_nim_is_built_from_the_codes_not_the_names(self):
        admission = self._register(self._applicant())
        self.assertTrue(
            admission.partner_id.nim.startswith(
                '%s-%s-' % (self.faculty.code, self.program.code),
            ),
        )

    def test_an_existing_student_keeps_their_nim(self):
        """A NIM is on a transcript, a card and every KHS already issued.

        Re-registering must not quietly hand the student a new one.
        """
        existing = self.env['res.partner'].create({
            'name': '%s Mahasiswa Lama' % TAG,
            'email': 'zz.lama@contoh.test',
            'is_student': True,
            'nim': '%s-LAMA-0001' % TAG,
            'program_id': self.program.id,
        })
        self._register(self._applicant(email='zz.lama@contoh.test'))
        self.assertEqual(existing.nim, '%s-LAMA-0001' % TAG)

    def test_reusing_a_student_does_not_burn_a_sequence_number(self):
        self.env['res.partner'].create({
            'name': '%s Mahasiswa Lama 2' % TAG,
            'email': 'zz.lama2@contoh.test',
            'is_student': True,
            'nim': '%s-LAMA-0002' % TAG,
            'program_id': self.program.id,
        })
        code = 'student.nim.%s-%s-' % (self.faculty.code, self.program.code)
        sequence = self.env['ir.sequence'].sudo().search([('code', '=like', code + '%')], limit=1)
        before = sequence.number_next_actual if sequence else None
        self._register(self._applicant(email='zz.lama2@contoh.test'))
        if sequence:
            sequence.invalidate_recordset()
            self.assertEqual(sequence.number_next_actual, before)

    def test_a_non_student_contact_is_never_renamed(self):
        """res.partner.email is not unique, so a vendor may share an address."""
        vendor = self.env['res.partner'].create({
            'name': '%s PT Vendor' % TAG, 'email': 'zz.vendor@contoh.test',
        })
        admission = self._register(self._applicant(email='zz.vendor@contoh.test'))
        self.assertEqual(vendor.name, '%s PT Vendor' % TAG)
        self.assertNotEqual(admission.partner_id, vendor)

    # --- the public form ---------------------------------------------------

    def test_the_public_form_refuses_a_programme_that_does_not_exist(self):
        """MissingError would hand an anonymous visitor the model, the record id
        and the internal uid."""
        with self.assertRaises(ValidationError):
            self.env['campus.admission'].sudo()._create_admission_from_portal({
                'name': 'X', 'email': 'zz.palsu@contoh.test', 'program_id': '99999999',
            })

    def test_the_public_form_refuses_a_programme_from_another_faculty(self):
        other_faculty = self.env['academic.faculty'].create({
            'name': '%s Fakultas Silang' % TAG, 'code': 'ZFS',
        })
        with self.assertRaises(ValidationError):
            self.env['campus.admission'].sudo()._create_admission_from_portal({
                'name': 'X', 'email': 'zz.silang@contoh.test',
                'faculty_id': str(other_faculty.id),
                'program_id': str(self.program.id),
            })

    def test_a_duplicate_application_is_reported_to_the_applicant(self):
        """Not as a system error: a UNIQUE violation is an IntegrityError and
        fell through the controller to the catch-all branch.

        Both applications go through the public form, because that is what
        decides which academic year they land in.
        """
        if not self.env['academic.year']._get_current():
            self.skipTest("no academic year is currently open for admission")
        payload = {
            'name': 'X', 'email': 'zz.ganda@contoh.test',
            'program_id': str(self.program.id),
        }
        self.env['campus.admission'].sudo()._create_admission_from_portal(dict(payload))
        self.env.flush_all()
        with self.assertRaises(ValidationError):
            self.env['campus.admission'].sudo()._create_admission_from_portal(dict(payload))

    # --- the checklist -----------------------------------------------------

    def test_the_document_checklist_arrives_with_the_record(self):
        admission = self._applicant(email='zz.checklist@contoh.test')
        self.assertEqual(
            len(admission.document_line_ids),
            len(self.env['campus.admission.document']._default_document_types()),
        )

    def test_documents_complete_is_stored_so_it_can_be_tracked(self):
        self.assertTrue(self.env['campus.admission']._fields['documents_complete'].store)

    def test_the_checklist_follows_the_admission_path(self):
        """The case the hard-coded list could not express: a transfer applicant
        brings a transcript from their previous institution, a school leaver
        has none."""
        Document = self.env['campus.admission.document']
        regular = Document._default_document_types('regular')
        transfer = Document._default_document_types('transfer')
        self.assertNotIn('transcript', regular)
        self.assertIn('transcript', transfer)

    def test_a_transfer_applicant_gets_the_extra_document(self):
        admission = self._applicant(email='zz.pindahan@contoh.test', admission_path='transfer')
        self.assertIn('transcript', admission.document_line_ids.mapped('document_type'))

    def test_the_checklist_is_configuration_not_code(self):
        """Adding a document must not need a code change."""
        self.env['campus.admission.requirement'].create({
            'document_type': 'other', 'admission_path': 'scholarship',
        })
        admission = self._applicant(email='zz.beasiswa@contoh.test', admission_path='scholarship')
        self.assertIn('other', admission.document_line_ids.mapped('document_type'))
