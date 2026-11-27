from psycopg2.errors import UniqueViolation

from odoo.tests.common import tagged
from odoo.tools import mute_logger

from .common import CampusCommon


@tagged('post_install', '-at_install')
class TestThresholdBands(CampusCommon):
    """academic.credit.limit and academic.grade.scale: single-company lookups."""

    def test_two_credit_bands_cannot_start_at_the_same_cgpa(self):
        band = self.env['academic.credit.limit'].search([], limit=1)
        self.assertTrue(band, "the module ships default credit limit bands")
        with mute_logger('odoo.sql_db'), self.assertRaises(UniqueViolation), self.cr.savepoint():
            self.env['academic.credit.limit'].create({
                'min_cgpa': band.min_cgpa, 'max_credits': 99,
            })
            self.env.flush_all()

    def test_two_grade_bands_cannot_start_at_the_same_score(self):
        band = self.env['academic.grade.scale'].search([], limit=1)
        with mute_logger('odoo.sql_db'), self.assertRaises(UniqueViolation), self.cr.savepoint():
            self.env['academic.grade.scale'].create({
                'min_score': band.min_score, 'letter': 'Z', 'grade_point': 1.0,
            })
            self.env.flush_all()

    def test_the_lookup_takes_the_highest_band_the_value_reaches(self):
        Scale = self.env['academic.grade.scale']
        top = Scale.search([], order='min_score desc', limit=1)
        letter, point = Scale._get_grade(100.0)
        self.assertEqual((letter, point), (top.letter, top.grade_point))

    def test_an_unconfigured_scale_falls_back_instead_of_crashing(self):
        """A lecturer mid-entry must not be stopped by a half-set-up campus."""
        self.assertEqual(
            self.env['academic.grade.scale']._get_grade(-1.0), ('E', 0.0),
        )

    def test_the_credit_cap_comes_from_the_configured_bands(self):
        Limits = self.env['academic.credit.limit']
        top_cap = Limits._get_max_credits(4.0)
        floor_cap = Limits._get_max_credits(0.0)
        band_200_cap = Limits._get_max_credits(2.0)
        self.assertTrue(top_cap and floor_cap and floor_cap < band_200_cap <= top_cap)
        # Freshmen with zero graded credits receive the top configured band.
        krs = self._make_krs()
        self.assertEqual(krs._get_max_credits_allowed(), top_cap)
        # Once graded with a low CGPA (< 2.00), the student drops to the floor band.
        krs.action_submit()
        krs.action_approve()
        krs.action_lock()
        khs = self.env['academic.khs'].search([
            ('student_id', '=', self.student.id),
            ('academic_year_id', '=', self.year.id),
        ], limit=1)
        khs.line_ids.write({'numeric_grade': 45.0})
        next_krs = self._make_krs(year=self.year_retake, schedules=self.schedule_retake)
        self.assertEqual(next_krs._get_max_credits_allowed(), floor_cap)
