from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .common import CampusCommon


@tagged('post_install', '-at_install')
class TestGpa(CampusCommon):
    """How a term GPA and a CGPA are built, and what must not count."""

    def _locked_krs_with_khs(self):
        krs = self._make_krs()
        krs.action_submit()
        krs.action_approve()
        krs.action_lock()
        khs = self.env['academic.khs'].search([
            ('student_id', '=', self.student.id),
            ('academic_year_id', '=', self.year.id),
        ], limit=1)
        return krs, khs

    def test_ungraded_lines_do_not_sink_the_cgpa(self):
        """Locking a KRS generates an empty KHS; it must not read as all E.

        A Float grade defaults to 0.0, which converts to an E worth 0 points, so
        counting ungraded lines dropped the student's CGPA the moment their plan
        was locked and cut next term's credit limit with it.
        """
        self.student.invalidate_recordset()
        cgpa_before = self.student.cgpa
        _krs, khs = self._locked_krs_with_khs()
        self.student.invalidate_recordset()

        self.assertTrue(khs.line_ids, "locking should generate the grade lines")
        self.assertFalse(any(khs.line_ids.mapped('is_graded')))
        self.assertEqual(khs.graded_credits, 0)
        self.assertEqual(khs.term_gpa, 0.0)
        self.assertGreater(khs.total_credits, 0, "credits taken are still shown")
        self.assertEqual(self.student.cgpa, cgpa_before, "CGPA must not move")

    def test_grading_a_line_marks_it_graded(self):
        _krs, khs = self._locked_krs_with_khs()
        line = khs.line_ids[0]
        line.write({'numeric_grade': 85.0})
        self.assertTrue(line.is_graded)
        self.assertEqual(line.letter_grade, 'A')
        self.assertEqual(line.grade_points, 4.0)
        self.assertEqual(khs.graded_credits, line.credits)
        self.assertEqual(khs.term_gpa, 4.0)

    def test_retake_counts_once_with_the_better_grade(self):
        """A repeat replaces the earlier attempt instead of joining it."""
        _krs, khs = self._locked_krs_with_khs()
        failed = khs.line_ids[0]
        failed.write({'numeric_grade': 20.0})
        self.assertEqual(failed.letter_grade, 'E')

        retake_khs = self.env['academic.khs'].create({
            'student_id': self.student.id,
            'academic_year_id': self.year_next.id,
            'line_ids': [(0, 0, {
                'subject_id': failed.subject_id.id,
                'numeric_grade': 90.0,
            })],
        })
        self.student.invalidate_recordset()

        recognised = self.student._recognised_khs_lines()
        subject_ids = [line.subject_id.id for line in recognised]
        self.assertEqual(
            subject_ids.count(failed.subject_id.id), 1,
            "a repeated subject must appear once",
        )
        self.assertEqual(self.student.cgpa, 4.0)
        self.assertEqual(self.student.graded_credits, failed.subject_id.credits)
        self.assertTrue(retake_khs.exists())

    def test_earned_credits_exclude_failures(self):
        _krs, khs = self._locked_krs_with_khs()
        khs.line_ids[0].write({'numeric_grade': 20.0})
        self.student.invalidate_recordset()
        self.assertGreater(self.student.graded_credits, 0)
        self.assertEqual(
            self.student.earned_credits, 0,
            "a failed subject is graded but not earned",
        )

    def test_khs_needs_an_approved_krs(self):
        with self.assertRaises(ValidationError):
            self.env['academic.khs'].create({
                'student_id': self.student.id,
                'academic_year_id': self.year_next.id,
            })

    def test_credits_are_a_snapshot(self):
        """Editing a subject's SKS must not rewrite plans already locked."""
        krs, khs = self._locked_krs_with_khs()
        before_krs = krs.total_credits
        before_khs = khs.line_ids[0].credits

        self.subject_a.credits = 1
        krs.invalidate_recordset()
        khs.invalidate_recordset()

        self.assertEqual(krs.total_credits, before_krs)
        self.assertEqual(khs.line_ids[0].credits, before_khs)
