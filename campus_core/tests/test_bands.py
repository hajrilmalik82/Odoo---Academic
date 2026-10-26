from psycopg2.errors import UniqueViolation

from odoo.tests.common import tagged
from odoo.tools import mute_logger

from .common import CampusCommon


@tagged('post_install', '-at_install')
class TestThresholdBands(CampusCommon):
    """academic.credit.limit and academic.grade.scale: the two lookup tables.

    Both declared UNIQUE (value, company_id), which PostgreSQL does not enforce
    across the company-less rows the module itself ships, because NULLs are
    distinct. Two bands at the same threshold then made the answer depend on row
    order - and the answers are a student's SKS cap and a printed letter grade.
    """

    def test_two_credit_bands_cannot_start_at_the_same_cgpa(self):
        band = self.env['academic.credit.limit'].search([('company_id', '=', False)], limit=1)
        self.assertTrue(band, "the module ships company-less bands")
        with mute_logger('odoo.sql_db'), self.assertRaises(UniqueViolation), self.cr.savepoint():
            self.env['academic.credit.limit'].create({
                'min_cgpa': band.min_cgpa, 'max_credits': 99, 'company_id': False,
            })
            self.env.flush_all()

    def test_two_grade_bands_cannot_start_at_the_same_score(self):
        band = self.env['academic.grade.scale'].search([('company_id', '=', False)], limit=1)
        with mute_logger('odoo.sql_db'), self.assertRaises(UniqueViolation), self.cr.savepoint():
            self.env['academic.grade.scale'].create({
                'min_score': band.min_score, 'letter': 'Z',
                'grade_point': 1.0, 'company_id': False,
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

    def test_a_company_band_outranks_the_shared_one_at_the_same_threshold(self):
        """But never overtakes a band with a higher threshold.

        Ordering by company first would have done exactly that: a company band
        at 0 would have won over a shared band at 85 for a score of 90.
        """
        Scale = self.env['academic.grade.scale']
        shared = Scale.search([('company_id', '=', False)], order='min_score desc', limit=1)
        own = Scale.create({
            'min_score': shared.min_score, 'letter': 'Z',
            'grade_point': 1.0, 'company_id': self.env.company.id,
        })
        self.env.flush_all()
        letter, _point = Scale._get_grade(shared.min_score + 1, company=self.env.company)
        self.assertEqual(letter, own.letter, "the institution's own band wins the tie")

        lower = Scale.search(
            [('min_score', '<', shared.min_score), ('company_id', '=', False)],
            order='min_score desc', limit=1,
        )
        if lower:
            letter, _point = Scale._get_grade(lower.min_score, company=self.env.company)
            self.assertEqual(
                letter, lower.letter,
                "a company band must not win below its own threshold",
            )

    def test_the_credit_cap_comes_from_the_configured_bands(self):
        cap = self.env['academic.credit.limit']._get_max_credits(0.0)
        self.assertTrue(cap and cap > 0)
        krs = self._make_krs()
        self.assertEqual(krs._get_max_credits_allowed(), cap)
