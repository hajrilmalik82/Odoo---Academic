from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import tagged

from .common import CampusCommon


@tagged('post_install', '-at_install')
class TestKrsSubmission(CampusCommon):
    """The submission rules, and the paths that used to get around them."""

    def test_submit_happy_path(self):
        krs = self._make_krs()
        krs.action_submit()
        self.assertEqual(krs.state, 'submitted')

    def test_submit_rejects_empty_krs(self):
        krs = self.env['academic.krs'].create({
            'student_id': self.student.id,
            'academic_year_id': self.year.id,
        })
        with self.assertRaises(ValidationError):
            krs.action_submit()

    def test_submit_rejects_inactive_student(self):
        self.student.student_status = 'leave'
        krs = self._make_krs()
        with self.assertRaises(ValidationError):
            krs.action_submit()

    def test_rules_run_on_a_raw_write(self):
        """The nine checks must not be reachable only through action_submit.

        Writing state directly was how a student could skip every rule, so the
        checks live in an @api.constrains and have to fire here too.
        """
        krs = self.env['academic.krs'].create({
            'student_id': self.student.id,
            'academic_year_id': self.year.id,
        })
        with self.assertRaises(ValidationError):
            krs.write({'state': 'submitted'})

    def test_credit_limit_comes_from_configuration(self):
        """A tightened band must take effect without a code change."""
        self.env['academic.credit.limit'].search([]).unlink()
        self.env['academic.credit.limit'].create({'min_cgpa': 0.0, 'max_credits': 2})
        krs = self._make_krs()
        self.assertGreater(krs.total_credits, 2)
        with self.assertRaises(ValidationError):
            krs.action_submit()

    def test_lines_frozen_once_submitted(self):
        """A student must not be able to grow an approved plan afterwards."""
        krs = self._make_krs()
        krs.action_submit()
        other_class = self.env['academic.class'].create({
            'subject_id': self.subject_b.id,
            'academic_year_id': self.year.id,
            'start_date': self.year.krs_start_date,
        })
        other_schedule = self.env['academic.class.schedule'].create({
            'class_id': other_class.id, 'class_code': 'A',
            'day_of_week': '2', 'start_time': 13.0, 'end_time': 15.0,
            'room_id': self.room.id,
        })
        with self.assertRaises(ValidationError):
            self.env['academic.krs.line'].create({
                'krs_id': krs.id, 'schedule_id': other_schedule.id,
            })
        with self.assertRaises(ValidationError):
            krs.line_ids.unlink()

    def test_schedule_must_match_academic_year(self):
        krs = self.env['academic.krs'].create({
            'student_id': self.student.id,
            'academic_year_id': self.year_next.id,
        })
        with self.assertRaises(ValidationError):
            self.env['academic.krs.line'].create({
                'krs_id': krs.id, 'schedule_id': self.schedule.id,
            })

    def test_one_krs_per_student_and_year(self):
        """The SQL constraint has to exist, not just be declared."""
        self._make_krs()
        with self.assertRaises(Exception):
            self._make_krs()
            self.env.flush_all()

    def test_section_quota_excludes_own_krs(self):
        """A student must not be counted against the seat they already hold."""
        krs = self._make_krs()
        krs.action_submit()
        self.assertEqual(self.schedule._enrolled_count(), 1)
        self.assertEqual(self.schedule._enrolled_count(exclude_krs=krs), 0)
        # Re-validating the same KRS must not trip the quota on its own seat.
        krs._check_section_quota()

    def test_section_quota_blocks_when_full(self):
        self.room.capacity = 1
        krs = self._make_krs()
        krs.action_submit()
        other_student = self.env['res.partner'].create({
            'name': 'Citra', 'is_student': True, 'student_status': 'active',
            'program_id': self.program.id, 'academic_advisor_id': self.advisor.id,
        })
        krs_two = self._make_krs(student=other_student)
        with self.assertRaises(ValidationError):
            krs_two.action_submit()

    def test_draft_blocked_while_khs_exists(self):
        krs = self._make_krs()
        krs.action_submit()
        krs.action_approve()
        krs.action_lock()
        self.assertTrue(self.env['academic.khs'].search([
            ('student_id', '=', self.student.id),
            ('academic_year_id', '=', self.year.id),
        ]))
        krs.action_unlock()
        with self.assertRaises(ValidationError):
            krs.action_set_draft()

    def test_raw_write_to_draft_blocked_while_khs_exists(self):
        krs = self._make_krs()
        krs.action_submit()
        krs.action_approve()
        krs.action_lock()
        khs = self.env['academic.khs'].search([
            ('student_id', '=', self.student.id),
            ('academic_year_id', '=', self.year.id),
        ])
        self.assertTrue(khs)
        krs.action_unlock()
        with self.assertRaises(ValidationError):
            krs.write({'state': 'draft'})
        khs.unlink()
        krs.write({'state': 'draft'})
        self.assertEqual(krs.state, 'draft')

    def test_unlock_is_administrator_only(self):
        krs = self._make_krs()
        krs.action_submit()
        krs.action_approve()
        krs.action_lock()
        plain_user = self.env['res.users'].create({
            'name': 'Staf Biasa', 'login': 'staf.biasa.test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            krs.with_user(plain_user).action_unlock()

    def test_snapshot_fields_locked_after_submission_and_krs_line_requires_subject(self):
        other_program = self.env['academic.program'].create({
            'name': 'ZZTEST Prodi Snapshot',
            'code': 'ZSN',
            'faculty_id': self.faculty.id,
        })
        krs = self._make_krs()
        with self.assertRaises(ValidationError):
            self.env['academic.krs.line'].create({
                'krs_id': krs.id,
                'schedule_id': self.schedule.id,
                'subject_id': False,
            })
        krs.action_submit()
        with self.assertRaises(ValidationError):
            krs.write({'program_id': other_program.id})
        with self.assertRaises(ValidationError):
            krs.write({'faculty_id': self.faculty.id})

    def test_mass_submit_handles_revision_and_reset_to_draft_is_admin_only(self):
        lecturer_group = self.env.ref('campus_core.group_campus_lecturer')
        advisor_user = self.env['res.users'].create({
            'name': 'ZZTEST Advisor Reset',
            'login': 'zz.advisor.reset.test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id, lecturer_group.id])],
        })
        self.advisor.user_id = advisor_user
        krs = self._make_krs()
        krs.action_submit()
        krs.with_user(advisor_user).action_request_revision()
        self.assertEqual(krs.state, 'revision')

        with self.assertRaises(AccessError):
            krs.with_user(advisor_user).write({'state': 'draft'})
        with self.assertRaises(AccessError):
            krs.with_user(advisor_user).action_set_draft()

        mass_submit = self.env.ref('campus_core.action_krs_mass_submit')
        mass_submit.with_context(active_model='academic.krs', active_ids=krs.ids).run()
        self.assertEqual(krs.state, 'submitted')

    def test_falsy_name_draws_sequence_and_fractional_grade_scale_rows(self):
        krs = self.env['academic.krs'].create({
            'name': False,
            'student_id': self.student.id,
            'academic_year_id': self.year.id,
            'line_ids': [(0, 0, {'schedule_id': self.schedule.id})],
        })
        self.assertTrue(krs.name and krs.name != 'New')
        krs.action_submit()
        krs.action_approve()
        khs = self.env['academic.khs'].create({
            'name': False,
            'student_id': self.student.id,
            'academic_year_id': self.year.id,
        })
        self.assertTrue(khs.name and khs.name != 'New')

        Scale = self.env['academic.grade.scale']
        Scale.create({'min_score': 82.5, 'letter': 'A-', 'grade_point': 3.7})
        rows = Scale._get_scale_rows()
        below = next(row for idx, row in enumerate(rows) if idx > 0 and rows[idx - 1]['letter'] == 'A-')
        self.assertIn('82.49', below['range'])
