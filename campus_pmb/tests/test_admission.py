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
        admission.write({'registration_fee_paid': True})
        admission.action_accept()
        admission.write({'reregistration_fee_paid': True})
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

    def _account_for(self, partner, login):
        """A login that already exists in the system, pointing at this contact."""
        return self.env['res.users'].sudo().create({
            'name': partner.name,
            'login': login,
            'partner_id': partner.id,
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })

    def test_an_account_belonging_to_someone_who_is_not_a_student_is_refused(self):
        """The branch above the partner search, which runs first and wins.

        A lecturer enrolling on a postgraduate programme with their work
        address is ordinary here, and it used to turn their personnel contact
        into a student - listed under Students, writable by academic staff
        through rule_academic_staff_partner_write, with a NIM. res.users.login
        is unique, so there is no second account to create instead, and only
        the admissions desk can say whether this is the same person.
        """
        lecturer = self.env['res.partner'].create({
            'name': '%s Pak Dosen' % TAG, 'email': 'zz.dosen.pmb@contoh.test',
        })
        self._account_for(lecturer, 'zz.dosen.pmb@contoh.test')
        admission = self._applicant(email='zz.dosen.pmb@contoh.test')
        with self.assertRaises(UserError) as caught:
            self._register(admission)
        self.assertIn('zz.dosen.pmb@contoh.test', str(caught.exception))

    def test_the_refused_contact_is_left_exactly_as_it_was(self):
        """Refusing is only worth anything if nothing was written on the way."""
        lecturer = self.env['res.partner'].create({
            'name': '%s Bu Dosen' % TAG, 'email': 'zz.dosen2.pmb@contoh.test',
        })
        self._account_for(lecturer, 'zz.dosen2.pmb@contoh.test')
        with self.assertRaises(UserError):
            self._register(self._applicant(email='zz.dosen2.pmb@contoh.test'))
        self.assertFalse(lecturer.is_student)
        self.assertFalse(lecturer.nim)
        # Empty on purpose: the old branch wrote the admission's programme here.
        self.assertFalse(lecturer.program_id)

    def test_a_student_who_already_has_an_account_is_still_reused(self):
        """The guard must refuse the collision, not everybody. A student
        re-registering keeps their account, their contact and their NIM."""
        student = self.env['res.partner'].create({
            'name': '%s Mahasiswa Berakun' % TAG,
            'email': 'zz.berakun@contoh.test',
            'is_student': True,
            'nim': '%s-AKUN-0001' % TAG,
            'program_id': self.program.id,
        })
        user = self._account_for(student, 'zz.berakun@contoh.test')
        admission = self._register(self._applicant(email='zz.berakun@contoh.test'))
        self.assertEqual(admission.user_id, user)
        self.assertEqual(admission.partner_id, student)
        self.assertEqual(student.nim, '%s-AKUN-0001' % TAG)

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

    def test_an_optional_requirement_is_created_as_not_required(self):
        """Unchecking Required on a requirement must carry over to new applicants."""
        self.env['campus.admission.requirement'].create({
            'document_type': 'other',
            'admission_path': 'scholarship',
            'required': False,
        })
        admission = self._applicant(email='zz.opsional@contoh.test', admission_path='scholarship')
        other_line = admission.document_line_ids.filtered(lambda l: l.document_type == 'other')
        self.assertTrue(other_line)
        self.assertFalse(other_line.required)

    # --- admission fees (pendaftaran & daftar ulang) -----------------------

    def test_fees_are_computed_from_configuration(self):
        regular = self._applicant(email='zz.fee.reg@contoh.test', admission_path='regular')
        transfer = self._applicant(email='zz.fee.trf@contoh.test', admission_path='transfer')
        scholarship = self._applicant(email='zz.fee.sch@contoh.test', admission_path='scholarship')

        self.assertGreater(regular.registration_fee, 0)
        self.assertGreater(regular.reregistration_fee, 0)
        self.assertGreater(transfer.registration_fee, regular.registration_fee)
        self.assertEqual(scholarship.registration_fee, 0.0)
        self.assertEqual(scholarship.reregistration_fee, 0.0)

    def test_program_specific_reregistration_fee_overrides_default(self):
        self.env['campus.admission.fee'].create({
            'fee_type': 'reregistration',
            'admission_path': 'all',
            'program_id': self.program.id,
            'amount': 6750000.0,
        })
        admission = self._applicant(email='zz.fee.prodi@contoh.test', admission_path='regular')
        self.assertEqual(admission.reregistration_fee, 6750000.0)

    def test_accept_requires_registration_fee_paid(self):
        admission = self._applicant(email='zz.belum.bayar.reg@contoh.test', admission_path='regular')
        admission.action_submit()
        admission.action_start_document_review()
        admission.document_line_ids.write({'received': True})
        with self.assertRaises(UserError):
            admission.action_accept()
        admission.registration_fee_paid = True
        admission.action_accept()
        self.assertEqual(admission.state, 'accepted')

    def test_register_requires_reregistration_fee_paid(self):
        admission = self._applicant(email='zz.belum.bayar.du@contoh.test', admission_path='regular')
        admission.action_submit()
        admission.action_start_document_review()
        admission.document_line_ids.write({'received': True})
        admission.registration_fee_paid = True
        admission.action_accept()
        with self.assertRaises(UserError):
            admission.action_register()
        admission.reregistration_fee_paid = True
        admission.action_register()
        self.assertEqual(admission.state, 'registered')

    def test_zero_fee_scholarship_does_not_require_payment_checkbox(self):
        admission = self._applicant(email='zz.gratis.beasiswa@contoh.test', admission_path='scholarship')
        admission.action_submit()
        admission.action_start_document_review()
        admission.document_line_ids.write({'received': True})
        admission.action_accept()
        admission.action_register()
        self.assertEqual(admission.state, 'registered')

    def test_phone_validation_accepts_valid_and_rejects_invalid(self):
        admission = self._applicant(email='zz.telepon.valid@contoh.test')
        admission.phone = '+62 812-3456-7890'
        self.assertEqual(admission.phone, '+62 812-3456-7890')
        with self.assertRaises(ValidationError):
            admission.phone = 'bukan-nomor-telepon'

    def test_renaming_institution_keeps_generated_nim_prefix(self):
        before, _year = self.env['campus.admission']._generate_nim(
            self.faculty, self.program, self.year,
        )
        self.faculty.name = '%s Fakultas Baru' % TAG
        self.program.name = '%s Program Baru' % TAG
        after, _year = self.env['campus.admission']._generate_nim(
            self.faculty, self.program, self.year,
        )
        self.assertEqual(before.rsplit('-', 1)[0], after.rsplit('-', 1)[0])

    def test_faculty_program_mismatch_and_invalid_email_rejected(self):
        other_faculty = self.env['academic.faculty'].create({
            'name': '%s Fakultas Mismatch' % TAG, 'code': 'ZFM',
        })
        with self.assertRaises(ValidationError):
            self._applicant(
                email='zz.mismatch@contoh.test',
                faculty_id=other_faculty.id,
                program_id=self.program.id,
            )
        with self.assertRaises(ValidationError):
            self._applicant(email='not-an-email')

    def test_re_reject_blocked_and_activities_follow_workflow(self):
        doc_act = self.env.ref('campus_pmb.mail_activity_type_document_review')
        pay_act = self.env.ref('campus_pmb.mail_activity_type_payment_verification')
        acc_act = self.env.ref('campus_pmb.mail_activity_type_create_account')

        adm_reject = self._applicant(email='zz.reject.twice@contoh.test')
        adm_reject.action_submit()
        self.assertTrue(adm_reject.activity_ids.filtered(lambda a: a.activity_type_id == doc_act))
        adm_reject.action_reject()
        self.assertFalse(adm_reject.activity_ids)
        with self.assertRaises(UserError):
            adm_reject.action_reject()

        adm = self._applicant(email='zz.activity.flow@contoh.test', admission_path='regular')
        adm.action_submit()
        self.assertTrue(adm.activity_ids.filtered(lambda a: a.activity_type_id == pay_act))
        adm.action_start_document_review()
        adm.document_line_ids.write({'received': True})
        adm.registration_fee_paid = True
        adm.action_accept()
        self.assertTrue(adm.activity_ids.filtered(lambda a: a.activity_type_id == acc_act))
        adm.reregistration_fee_paid = True
        adm.action_register()
        self.assertFalse(adm.activity_ids)

    def test_post_acceptance_locks_and_path_checklist_sync(self):
        adm = self._applicant(email='zz.sync.path@contoh.test', admission_path='transfer')
        self.assertIn('transcript', adm.document_line_ids.mapped('document_type'))
        adm.write({'admission_path': 'regular'})
        self.assertNotIn('transcript', adm.document_line_ids.mapped('document_type'))

        adm.action_submit()
        adm.action_start_document_review()
        adm.document_line_ids.write({'received': True})
        adm.registration_fee_paid = True
        adm.action_accept()

        with self.assertRaises(ValidationError):
            adm.write({'program_id': self.program.id})
        with self.assertRaises(ValidationError):
            adm.document_line_ids[0].write({'received': False})

        # Re-registration payment remains editable while accepted until registered
        adm.reregistration_fee_paid = True
        adm.action_register()
        with self.assertRaises(ValidationError):
            adm.write({'reregistration_fee_paid': False})

    def test_pmb_activity_assignee_respects_faculty_jurisdiction(self):
        """An officer with all_programs=True on Faculty A must not get activities for Faculty B."""
        pmb_group = self.env.ref('campus_pmb.group_pmb')
        internal_group = self.env.ref('base.group_user')
        other_faculty = self.env['academic.faculty'].create({
            'name': '%s Fakultas Ekonomi C9' % TAG, 'code': 'ZEC',
        })
        other_program = self.env['academic.program'].create({
            'name': '%s Manajemen C9' % TAG, 'code': 'ZMC',
            'faculty_id': other_faculty.id,
        })
        officer_a_user = self.env['res.users'].create({
            'name': '%s PMB FTI' % TAG, 'login': 'zz.pmb.fti.c9@contoh.test',
            'group_ids': [(6, 0, [internal_group.id, pmb_group.id])],
        })
        officer_a_emp = self.env['hr.employee'].create({
            'name': '%s PMB FTI' % TAG, 'academic_role': 'pmb',
            'user_id': officer_a_user.id,
        })
        self.env['campus.jurisdiction'].create({
            'employee_id': officer_a_emp.id, 'scope': 'pmb',
            'faculty_ids': [(6, 0, [self.faculty.id])], 'all_programs': True,
        })

        adm_other = self._applicant(
            email='zz.c9.feb1@contoh.test',
            faculty_id=other_faculty.id, program_id=other_program.id,
        )
        adm_other.action_submit()
        self.assertTrue(adm_other.activity_ids)
        self.assertNotIn(officer_a_user, adm_other.activity_ids.mapped('user_id'))
        self.assertEqual(set(adm_other.activity_ids.mapped('user_id').ids), {self.env.user.id})

        officer_b_user = self.env['res.users'].create({
            'name': '%s PMB FEB' % TAG, 'login': 'zz.pmb.feb.c9@contoh.test',
            'group_ids': [(6, 0, [internal_group.id, pmb_group.id])],
        })
        officer_b_emp = self.env['hr.employee'].create({
            'name': '%s PMB FEB' % TAG, 'academic_role': 'pmb',
            'user_id': officer_b_user.id,
        })
        self.env['campus.jurisdiction'].create({
            'employee_id': officer_b_emp.id, 'scope': 'pmb',
            'faculty_ids': [(6, 0, [other_faculty.id])], 'all_programs': True,
        })
        adm_other_2 = self._applicant(
            email='zz.c9.feb2@contoh.test',
            faculty_id=other_faculty.id, program_id=other_program.id,
        )
        adm_other_2.action_submit()
        self.assertEqual(set(adm_other_2.activity_ids.mapped('user_id').ids), {officer_b_user.id})
