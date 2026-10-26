from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .common import TAG, CampusCommon


@tagged('post_install', '-at_install')
class TestSectionCapacity(CampusCommon):
    """Seats are counted once, in one place, and the same way everywhere.

    "Enrolled" used to be spelled out three different ways, so the figure the
    validator blocked on and the figure shown on screen disagreed.
    """

    def _student(self, suffix):
        return self.env['res.partner'].create({
            'name': '%s Mahasiswa %s' % (TAG, suffix),
            'is_student': True,
            'student_status': 'active',
            'program_id': self.program.id,
            'academic_advisor_id': self.advisor.id,
        })

    def _submitted_krs(self, student):
        krs = self._make_krs(student=student)
        krs.action_submit()
        return krs

    def test_the_room_capacity_is_the_limit(self):
        """The fixture room seats two."""
        self.assertEqual(self.schedule.room_capacity, 2)
        self._submitted_krs(self.student)
        self._submitted_krs(self._student('B'))
        self.assertEqual(self.schedule._enrolled_count(), 2)

        third = self._make_krs(student=self._student('C'))
        with self.assertRaises(ValidationError):
            third.action_submit()

    def test_a_draft_plan_does_not_take_a_seat(self):
        """Only submitted and above count, so a draft cannot hold a place."""
        self._make_krs(student=self._student('D'))
        self.assertEqual(self.schedule._enrolled_count(), 0)

    def test_a_student_is_not_counted_against_their_own_seat(self):
        krs = self._submitted_krs(self.student)
        self.assertEqual(self.schedule._enrolled_count(), 1)
        self.assertEqual(self.schedule._enrolled_count(exclude_krs=krs), 0)

    def test_the_batched_count_agrees_with_the_single_one(self):
        """_compute_capacity_display reads the batched form; the validator the single.

        They are the same number by construction - the single-record call is a
        wrapper - and this is what stops them drifting apart again.
        """
        self._submitted_krs(self.student)
        counts = self.schedule._enrolled_counts()
        self.assertEqual(counts[self.schedule.id], self.schedule._enrolled_count())
        self.assertEqual(self.schedule.enrolled_count, counts[self.schedule.id])

    def test_the_batched_count_answers_for_every_record_asked(self):
        """Including sections nobody has enrolled in, which must read 0, not be absent."""
        schedules = self.schedule | self.schedule_retake
        counts = schedules._enrolled_counts()
        self.assertEqual(set(counts), set(schedules.ids))
        self.assertEqual(counts[self.schedule_retake.id], 0)

    def test_reserving_states_can_be_asked_for(self):
        """The mass-assign wizard writes schedules onto DRAFT lines.

        With the strict count it could not see its own previous run and the same
        room could be filled twice over.
        """
        self._make_krs(student=self._student('E'))
        strict = self.schedule._enrolled_count()
        reserving = self.schedule._enrolled_count(
            states=self.env['academic.krs']._EDITABLE_STATES
                   + self.schedule._ENROLLED_KRS_STATES,
        )
        self.assertEqual(strict, 0)
        self.assertEqual(reserving, 1)
