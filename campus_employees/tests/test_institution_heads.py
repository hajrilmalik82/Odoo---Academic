from odoo.exceptions import ValidationError
from odoo.tests.common import tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.campus_core.tests.common import TAG, CampusCommon


@tagged('post_install', '-at_install')
class TestInstitutionHeads(CampusCommon):
    """Only a lecturer of the unit may head it.

    Two mechanisms, tested separately because they fail separately: the field
    domain decides what the dropdown offers, and the constraint decides what can
    actually be stored. A domain alone would leave an import free to write
    anybody into the field.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Codes spelled out rather than left to _derive_code, the way the shared
        # fixture does it: they are unique per company, and two derived codes
        # colliding would fail the setUp for a reason that has nothing to do
        # with what is under test here.
        cls.other_faculty = cls.env['academic.faculty'].create({
            'name': '%s Fakultas Lain' % TAG,
            'code': 'ZFL',
        })
        cls.other_program = cls.env['academic.program'].create({
            'name': '%s Program Lain' % TAG,
            'code': 'ZPL',
            'faculty_id': cls.other_faculty.id,
        })

        cls.own_lecturer = cls.env['hr.employee'].create({
            'name': '%s Dosen Sendiri' % TAG,
            'academic_role': 'lecturer',
            'faculty_id': cls.faculty.id,
            'program_id': cls.program.id,
        })
        cls.outside_lecturer = cls.env['hr.employee'].create({
            'name': '%s Dosen Fakultas Lain' % TAG,
            'academic_role': 'lecturer',
            'faculty_id': cls.other_faculty.id,
            'program_id': cls.other_program.id,
        })
        cls.staff = cls.env['hr.employee'].create({
            'name': '%s Staf TU' % TAG,
            'academic_role': 'academic',
            'faculty_id': cls.faculty.id,
            'program_id': cls.program.id,
        })

    def _candidates(self, model, field_name, record_id):
        """What the dropdown would offer: the field's own domain, evaluated the
        way a form view evaluates it."""
        domain = safe_eval(self.env[model]._fields[field_name].domain, {'id': record_id})
        return self.env['hr.employee'].search(domain)

    # --- what the dropdown offers ----------------------------------------

    def test_the_dean_list_holds_only_lecturers_of_that_faculty(self):
        candidates = self._candidates('academic.faculty', 'dean_id', self.faculty.id)
        self.assertIn(self.own_lecturer, candidates)
        self.assertNotIn(self.outside_lecturer, candidates)
        self.assertNotIn(self.staff, candidates, "academic staff are not lecturers")
        self.assertNotIn(self.advisor, candidates, "a lecturer with no faculty is not a member")

    def test_the_head_list_holds_only_lecturers_of_that_programme(self):
        candidates = self._candidates('academic.program', 'head_id', self.program.id)
        self.assertIn(self.own_lecturer, candidates)
        self.assertNotIn(self.outside_lecturer, candidates)
        self.assertNotIn(self.staff, candidates)

    def test_an_unsaved_record_offers_nobody(self):
        """`id` is False on a record being created, and the equality alone would
        then read as ('faculty_id', '=', False) - offering every lecturer who has
        no faculty yet."""
        self.assertFalse(self._candidates('academic.faculty', 'dean_id', False))
        self.assertFalse(self._candidates('academic.program', 'head_id', False))

    # --- what can actually be stored --------------------------------------

    def test_a_lecturer_of_the_faculty_can_be_made_dean(self):
        self.faculty.dean_id = self.own_lecturer
        self.assertEqual(self.faculty.dean_id, self.own_lecturer)

    def test_a_lecturer_of_the_programme_can_be_made_head(self):
        self.program.head_id = self.own_lecturer
        self.assertEqual(self.program.head_id, self.own_lecturer)

    def test_a_lecturer_from_another_faculty_cannot_be_dean(self):
        with self.assertRaises(ValidationError):
            self.faculty.dean_id = self.outside_lecturer

    def test_a_lecturer_from_another_programme_cannot_be_head(self):
        with self.assertRaises(ValidationError):
            self.program.head_id = self.outside_lecturer

    def test_academic_staff_cannot_be_dean(self):
        with self.assertRaises(ValidationError):
            self.faculty.dean_id = self.staff

    def test_academic_staff_cannot_be_head(self):
        with self.assertRaises(ValidationError):
            self.program.head_id = self.staff

    def test_clearing_the_head_stays_allowed(self):
        """The constraint must not stand in the way of vacating the post."""
        self.program.head_id = self.own_lecturer
        self.program.head_id = False
        self.assertFalse(self.program.head_id)

    # --- the same rule, read from the employee's side ---------------------
    #
    # Writing the person instead of the post is the hole the two constraints
    # above cannot see: they only fire when the faculty or the programme is
    # written.

    def test_a_sitting_head_cannot_be_moved_to_another_programme(self):
        self.program.head_id = self.own_lecturer
        with self.assertRaises(ValidationError) as caught:
            self.own_lecturer.program_id = self.other_program
        self.assertIn(self.program.name, str(caught.exception),
                      "the message must name the post being held")

    def test_a_sitting_dean_cannot_be_moved_to_another_faculty(self):
        self.faculty.dean_id = self.own_lecturer
        with self.assertRaises(ValidationError) as caught:
            self.own_lecturer.faculty_id = self.other_faculty
        self.assertIn(self.faculty.name, str(caught.exception))

    def test_a_sitting_head_cannot_stop_being_a_lecturer(self):
        """Demotion is a move too: the post requires a lecturer."""
        self.program.head_id = self.own_lecturer
        with self.assertRaises(ValidationError):
            self.own_lecturer.academic_role = 'academic'

    def test_vacating_the_post_first_lets_the_move_through(self):
        """What the refusal tells the user to do has to actually work."""
        self.program.head_id = self.own_lecturer
        self.program.head_id = False
        self.own_lecturer.program_id = self.other_program
        self.assertEqual(self.own_lecturer.program_id, self.other_program)

    def test_an_employee_holding_no_post_moves_freely(self):
        self.staff.faculty_id = self.other_faculty
        self.assertEqual(self.staff.faculty_id, self.other_faculty)
