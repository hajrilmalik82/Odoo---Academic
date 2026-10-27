from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from odoo.addons.campus_core.tests.common import TAG, CampusCommon


@tagged('post_install', '-at_install')
class TestLecturerMove(CampusCommon):
    """Moving somebody between faculties or programmes.

    The rule is deliberately blunt: while anything still points at them, the
    move is refused and the refusal names what. It is stricter than the teaching
    rule, which allows a lecturer to teach across programmes inside their own
    faculty - so a move that teaching would have tolerated is still stopped. That
    is the behaviour that was asked for: nothing moves while it is still wired
    up, and the user is told what to unwire.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.elsewhere = cls.env['academic.faculty'].create({
            'name': '%s Fakultas Seberang' % TAG,
            'code': 'ZFS',
        })
        cls.elsewhere_program = cls.env['academic.program'].create({
            'name': '%s Program Seberang' % TAG,
            'code': 'ZPS',
            'faculty_id': cls.elsewhere.id,
        })

        cls.mover = cls.env['hr.employee'].create({
            'name': '%s Dosen Pindah' % TAG,
            'academic_role': 'lecturer',
            'faculty_id': cls.faculty.id,
            'program_id': cls.program.id,
        })

    def _teaches(self):
        self.schedule.lecturer_id = self.mover

    def _advises(self):
        return self.env['res.partner'].create({
            'name': '%s Mahasiswa Bimbingan' % TAG,
            'is_student': True,
            'student_status': 'active',
            'program_id': self.program.id,
            'academic_advisor_id': self.mover.id,
        })

    # --- what blocks a move -----------------------------------------------

    def test_teaching_a_class_blocks_the_move(self):
        self._teaches()
        with self.assertRaises(ValidationError) as caught:
            self.mover.program_id = self.elsewhere_program
        self.assertIn(self.subject_a.name, str(caught.exception),
                      "the refusal must name the subject being taught")

    def test_advising_a_student_blocks_the_move(self):
        student = self._advises()
        with self.assertRaises(ValidationError) as caught:
            self.mover.faculty_id = self.elsewhere
        self.assertIn(student.name, str(caught.exception),
                      "the refusal must name who is being advised")

    def test_clearing_the_faculty_counts_as_a_move(self):
        self._teaches()
        with self.assertRaises(ValidationError):
            self.mover.faculty_id = False

    def test_losing_the_lecturer_role_counts_as_a_move(self):
        self._teaches()
        with self.assertRaises(ValidationError):
            self.mover.academic_role = 'academic'

    def test_the_refusal_lists_everything_at_once(self):
        """Being told about one attachment, fixing it, and then being told about
        a second is worse than being handed the whole list."""
        self.program.head_id = self.mover
        self._teaches()
        student = self._advises()
        with self.assertRaises(ValidationError) as caught:
            self.mover.faculty_id = self.elsewhere
        message = str(caught.exception)
        self.assertIn(self.program.name, message, "the post is missing")
        self.assertIn(self.subject_a.name, message, "the teaching is missing")
        self.assertIn(student.name, message, "the advisee is missing")

    # --- what does not block a move ---------------------------------------

    def test_filling_the_profile_in_for_the_first_time_is_not_a_move(self):
        """campus_core builds the teaching schedule, and campus_employees only
        afterwards says which faculty and programme those lecturers belong to.
        Counting an empty-to-set write as a move would refuse the demo data this
        suite ships with."""
        self.schedule.lecturer_id = self.advisor
        self.assertFalse(self.advisor.faculty_id, "fixture precondition")
        self.advisor.faculty_id = self.faculty
        self.assertEqual(self.advisor.faculty_id, self.faculty)

    def test_writing_the_same_value_again_is_not_a_move(self):
        """A constraint cannot see the previous value, so it would refuse a
        re-save that changes nothing. This guard can, and does not."""
        self._teaches()
        self.mover.write({
            'faculty_id': self.faculty.id,
            'program_id': self.program.id,
            'academic_role': 'lecturer',
        })
        self.assertEqual(self.mover.program_id, self.program)

    def test_an_untouched_field_does_not_trigger_the_check(self):
        """Editing something unrelated on a busy lecturer must stay possible."""
        self._teaches()
        self.mover.nidn = '0011223344'
        self.assertEqual(self.mover.nidn, '0011223344')

    def test_reassigning_first_lets_the_move_through(self):
        """What the refusal tells the user to do has to actually work."""
        self._teaches()
        student = self._advises()
        self.schedule.lecturer_id = False
        student.academic_advisor_id = False
        self.mover.program_id = self.elsewhere_program
        self.assertEqual(self.mover.program_id, self.elsewhere_program)
