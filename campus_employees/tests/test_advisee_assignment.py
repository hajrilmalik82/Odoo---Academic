from odoo.exceptions import ValidationError
from odoo.tests.common import tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.campus_core.tests.common import TAG, CampusCommon


@tagged('post_install', '-at_install')
class TestAdviseeAssignment(CampusCommon):
    """Gaining an advisee by choosing an existing student.

    The Advisees counter used to open the contact list with Odoo's New button
    on it, which invited somebody to create a student from the lecturer's card.
    Students arrive through the admissions flow in campus_pmb, which is what
    issues the NIM and links the programme. Creation is off on that list now,
    and this wizard is what takes its place.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.lecturer = cls.env['hr.employee'].create({
            'name': '%s Dosen Wali' % TAG,
            'academic_role': 'lecturer',
            'faculty_id': cls.faculty.id,
            'program_id': cls.program.id,
        })
        cls.unassigned = cls.env['res.partner'].create({
            'name': '%s Mahasiswa Tanpa Wali' % TAG,
            'is_student': True,
            'student_status': 'active',
            'program_id': cls.program.id,
        })
        cls.someone_elses = cls.env['res.partner'].create({
            'name': '%s Mahasiswa Wali Lain' % TAG,
            'is_student': True,
            'student_status': 'active',
            'program_id': cls.program.id,
            'academic_advisor_id': cls.advisor.id,
        })
        cls.already_mine = cls.env['res.partner'].create({
            'name': '%s Mahasiswa Sudah Saya' % TAG,
            'is_student': True,
            'student_status': 'active',
            'program_id': cls.program.id,
            'academic_advisor_id': cls.lecturer.id,
        })
        cls.graduated = cls.env['res.partner'].create({
            'name': '%s Mahasiswa Lulus' % TAG,
            'is_student': True,
            'student_status': 'graduated',
            'program_id': cls.program.id,
        })

        cls.far_program = cls.env['academic.program'].create({
            'name': '%s Prodi Seberang' % TAG,
            'code': 'ZPB',
            'faculty_id': cls.faculty.id,
        })
        cls.far_lecturer = cls.env['hr.employee'].create({
            'name': '%s Dosen Seberang' % TAG,
            'academic_role': 'lecturer',
            'faculty_id': cls.faculty.id,
            'program_id': cls.far_program.id,
        })
        cls.far_student = cls.env['res.partner'].create({
            'name': '%s Mahasiswa Seberang' % TAG,
            'is_student': True,
            'student_status': 'active',
            'program_id': cls.far_program.id,
        })

    def _wizard(self, students=None):
        return self.env['campus.advisee.assign'].with_context(
            active_model='hr.employee', active_id=self.lecturer.id,
        ).create({'student_ids': [(6, 0, (students or self.env['res.partner']).ids)]})

    # --- no creating students from here -----------------------------------

    def test_the_advisee_list_cannot_create(self):
        self.assertFalse(self.lecturer.action_open_advisees()['context'].get('create'))

    def test_neither_can_the_schedule_or_session_lists(self):
        """A schedule belongs to a class and a session is generated from a
        schedule; neither means anything made from here."""
        for action in (self.lecturer.action_open_schedules(),
                       self.lecturer.action_open_sessions()):
            with self.subTest(model=action['res_model']):
                self.assertFalse(action['context'].get('create'))

    # --- choosing an existing student instead -----------------------------

    def test_the_wizard_takes_its_advisor_from_the_employee_it_opened_on(self):
        self.assertEqual(self._wizard().advisor_id, self.lecturer)

    def test_assigning_points_the_students_at_the_advisor(self):
        wizard = self._wizard(self.unassigned | self.someone_elses)
        wizard.action_assign()
        self.assertEqual(self.unassigned.academic_advisor_id, self.lecturer)
        self.assertEqual(self.someone_elses.academic_advisor_id, self.lecturer,
                         "reassigning away from another advisor is allowed")

    def test_assigning_nobody_is_refused(self):
        with self.assertRaises(ValidationError):
            self._wizard().action_assign()

    def test_the_counter_follows_the_assignment(self):
        before = self.lecturer.advisee_count
        self._wizard(self.unassigned).action_assign()
        self.lecturer.invalidate_recordset()
        self.assertEqual(self.lecturer.advisee_count, before + 1)

    # --- who the wizard offers --------------------------------------------

    def _offered(self):
        """What the picker would offer, evaluated the way a form evaluates it.

        The evaluation context is built from every field on the wizard rather
        than from a hand-written pair. A domain names whatever it likes, and a
        variable left out of the context is a NameError rather than a narrower
        list - which is how adding one programme clause to the domain broke all
        six of these tests at once, while the feature itself was fine.
        """
        wizard = self._wizard()
        context = {}
        for name, field in wizard._fields.items():
            value = wizard[name]
            if field.type == 'many2one':
                context[name] = value.id
            elif field.type in ('one2many', 'many2many'):
                context[name] = value.ids
            else:
                context[name] = value
        domain = safe_eval(wizard._fields['student_ids'].domain, context)
        return self.env['res.partner'].search(domain)

    def test_students_without_an_advisor_are_offered(self):
        """An inequality on a many2one reads as "different, or not set" in Odoo,
        which is what lets these through."""
        self.assertIn(self.unassigned, self._offered())

    def test_students_of_another_advisor_are_offered(self):
        self.assertIn(self.someone_elses, self._offered())

    def test_students_this_advisor_already_has_are_not_offered(self):
        self.assertNotIn(self.already_mine, self._offered())

    def test_a_graduated_student_is_not_offered(self):
        self.assertNotIn(self.graduated, self._offered())

    def test_a_contact_who_is_not_a_student_is_not_offered(self):
        contact = self.env['res.partner'].create({'name': '%s Kontak Biasa' % TAG})
        self.assertNotIn(contact, self._offered())

    def test_a_student_of_another_programme_is_not_offered(self):
        """An advisor belongs to the student's own programme, so offering one
        the wizard could not legally assign would be a trap."""
        self.assertNotIn(self.far_student, self._offered())

    # --- the rule the wizard follows --------------------------------------

    def test_an_advisor_must_share_the_students_programme(self):
        with self.assertRaises(ValidationError) as caught:
            self.unassigned.academic_advisor_id = self.far_lecturer
        message = str(caught.exception)
        self.assertIn(self.far_program.name, message)
        self.assertIn(self.program.name, message)

    def test_an_advisor_must_be_a_lecturer(self):
        staff = self.env['hr.employee'].create({
            'name': '%s Staf Wali' % TAG,
            'academic_role': 'academic',
            'faculty_id': self.faculty.id,
            'program_id': self.program.id,
        })
        with self.assertRaises(ValidationError):
            self.unassigned.academic_advisor_id = staff

    def test_moving_the_student_revalidates_the_advisor(self):
        """The quiet half of the rule: the advisor field is not touched, so a
        constraint watching it alone would never fire, and the student would
        keep an advisor from the programme they just left."""
        with self.assertRaises(ValidationError):
            self.already_mine.program_id = self.far_program

    def test_the_advisor_picker_offers_only_lecturers_of_that_programme(self):
        domain = safe_eval(
            self.env['res.partner']._fields['academic_advisor_id'].domain,
            {'program_id': self.program.id},
        )
        candidates = self.env['hr.employee'].search(domain)
        self.assertIn(self.lecturer, candidates)
        self.assertNotIn(self.far_lecturer, candidates)

    def test_a_student_with_no_programme_is_offered_no_advisor(self):
        """Otherwise the equality reads as ('program_id', '=', False) and
        offers every lecturer who has no programme either."""
        domain = safe_eval(
            self.env['res.partner']._fields['academic_advisor_id'].domain,
            {'program_id': False},
        )
        self.assertFalse(self.env['hr.employee'].search(domain))
