from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import tagged

from odoo.addons.campus_core.tests.common import TAG, CampusCommon


class ThesisFixtureMixin:
    """Shared fixtures and workflow helpers for thesis tests."""

    @classmethod
    def _setup_thesis_actors(cls):
        today = fields.Date.context_today(cls.env.user)

        cls.metopen_subject = cls.env['academic.subject'].create({
            'name': '%s Metodologi Penelitian' % TAG,
            'code': 'ZMP301',
            'credits': 3,
            'term_type': 'odd',
            'thesis_role': 'research_method',
            'program_id': cls.program.id,
        })
        cls.thesis_subject = cls.env['academic.subject'].create({
            'name': '%s Skripsi' % TAG,
            'code': 'ZSK401',
            'credits': 6,
            'term_type': 'odd',
            'thesis_role': 'thesis',
            'program_id': cls.program.id,
        })

        cls.thesis_room = cls.env['campus.room'].create({
            'name': '%s Ruang Skripsi' % TAG,
            'building_id': cls.building.id,
            'capacity': 20,
            'room_type': 'theory',
        })
        cls.metopen_class = cls.env['academic.class'].create({
            'subject_id': cls.metopen_subject.id,
            'academic_year_id': cls.year_retake.id,
            'start_date': today,
        })
        cls.metopen_schedule = cls.env['academic.class.schedule'].create({
            'class_id': cls.metopen_class.id,
            'class_code': 'A',
            'day_of_week': '3',
            'start_time': 13.0,
            'end_time': 15.0,
            'room_id': cls.thesis_room.id,
        })
        cls.thesis_class = cls.env['academic.class'].create({
            'subject_id': cls.thesis_subject.id,
            'academic_year_id': cls.year.id,
            'start_date': today,
        })
        cls.thesis_schedule = cls.env['academic.class.schedule'].create({
            'class_id': cls.thesis_class.id,
            'class_code': 'A',
            'day_of_week': '4',
            'start_time': 10.0,
            'end_time': 12.0,
            'room_id': cls.thesis_room.id,
        })

        base_group = cls.env.ref('base.group_user')
        cls.supervisor_user = cls.env['res.users'].create({
            'name': '%s Pembimbing Utama' % TAG,
            'login': 'zz.pembimbing1@contoh.test',
            'group_ids': [Command.set([base_group.id])],
        })
        cls.co_supervisor_user = cls.env['res.users'].create({
            'name': '%s Pembimbing Pendamping' % TAG,
            'login': 'zz.pembimbing2@contoh.test',
            'group_ids': [Command.set([base_group.id])],
        })
        cls.advisor_user = cls.env['res.users'].create({
            'name': '%s Dosen PA' % TAG,
            'login': 'zz.pa.thesis@contoh.test',
            'group_ids': [Command.set([base_group.id])],
        })
        cls.dean_user = cls.env['res.users'].create({
            'name': '%s Dekan FT' % TAG,
            'login': 'zz.dekan.thesis@contoh.test',
            'group_ids': [Command.set([base_group.id])],
        })
        cls.other_lecturer_user = cls.env['res.users'].create({
            'name': '%s Dosen Lain' % TAG,
            'login': 'zz.dosen.lain@contoh.test',
            'group_ids': [Command.set([base_group.id])],
        })

        cls.advisor.write({'user_id': cls.advisor_user.id})

        cls.supervisor_emp = cls.env['hr.employee'].create({
            'name': '%s Dr. Pembimbing 1' % TAG,
            'academic_role': 'lecturer',
            'faculty_id': cls.faculty.id,
            'program_id': cls.program.id,
            'user_id': cls.supervisor_user.id,
        })
        cls.co_supervisor_emp = cls.env['hr.employee'].create({
            'name': '%s Dr. Pembimbing 2' % TAG,
            'academic_role': 'lecturer',
            'faculty_id': cls.faculty.id,
            'program_id': cls.program.id,
            'user_id': cls.co_supervisor_user.id,
        })
        cls.dean_emp = cls.env['hr.employee'].create({
            'name': '%s Prof. Dekan' % TAG,
            'academic_role': 'lecturer',
            'faculty_id': cls.faculty.id,
            'program_id': cls.program.id,
            'user_id': cls.dean_user.id,
        })
        cls.other_lecturer_emp = cls.env['hr.employee'].create({
            'name': '%s Dosen Netral' % TAG,
            'academic_role': 'lecturer',
            'faculty_id': cls.faculty.id,
            'program_id': cls.program.id,
            'user_id': cls.other_lecturer_user.id,
        })
        cls.faculty.write({'dean_id': cls.dean_emp.id})

    def _record_metopen_grade(self, student, score=85.0, year=None):
        year = year or self.year_retake
        khs = self.env['academic.khs'].search([
            ('student_id', '=', student.id),
            ('academic_year_id', '=', year.id),
        ], limit=1)
        if not khs:
            krs = self.env['academic.krs'].create({
                'student_id': student.id,
                'academic_year_id': year.id,
                'line_ids': [Command.create({'schedule_id': self.metopen_schedule.id})],
            })
            krs.action_submit()
            krs.action_approve()
            krs.action_lock()
            khs = self.env['academic.khs'].search([
                ('student_id', '=', student.id),
                ('academic_year_id', '=', year.id),
            ], limit=1)
        line = khs.line_ids.filtered(lambda l: l.subject_id == self.metopen_subject)[:1]
        line.write({'numeric_grade': score, 'is_graded': True})
        return khs

    def _enroll_thesis_krs(self, student, approve=True, year=None):
        year = year or self.year
        krs = self.env['academic.krs'].search([
            ('student_id', '=', student.id),
            ('academic_year_id', '=', year.id),
        ], limit=1)
        if not krs:
            krs = self.env['academic.krs'].create({
                'student_id': student.id,
                'academic_year_id': year.id,
                'line_ids': [Command.create({'schedule_id': self.thesis_schedule.id})],
            })
        else:
            krs.write({
                'line_ids': [Command.create({'schedule_id': self.thesis_schedule.id})],
            })
        if approve:
            krs.action_submit()
            krs.action_approve()
        return krs

    def _make_thesis(self, student=None, co_supervisor=False, **overrides):
        student = student or self.student
        vals = {
            'student_id': student.id,
            'academic_year_id': self.year.id,
            'title': '%s Rancang Bangun Sistem Akademik' % TAG,
            'research_topic': 'Optimasi basis data akademik.',
            'supervisor_id': self.supervisor_emp.id,
        }
        if co_supervisor:
            vals['co_supervisor_id'] = self.co_supervisor_emp.id
        vals.update(overrides)
        return self.env['campus.thesis'].create(vals)


@tagged('post_install', '-at_install')
class TestThesisWorkflow(ThesisFixtureMixin, CampusCommon):
    """End-to-end thesis rules, gates, role checks, sequential Yudisium, and Wisuda."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_thesis_actors()

    def test_cannot_register_without_research_methodology_grade(self):
        with self.assertRaises(ValidationError):
            self._make_thesis()

    def test_cannot_register_when_research_methodology_failed(self):
        self._record_metopen_grade(self.student, score=40.0)  # Grade E = 0.0 < 2.0
        with self.assertRaises(ValidationError):
            self._make_thesis()

    def test_can_register_after_passing_research_methodology(self):
        self._record_metopen_grade(self.student, score=82.0)
        thesis = self._make_thesis()
        self.assertEqual(thesis.state, 'draft')
        self.assertTrue(thesis.name.startswith('SKR/'))
        self.assertTrue(thesis.research_method_passed)

    def test_only_one_active_thesis_per_student(self):
        self._record_metopen_grade(self.student, score=82.0)
        first = self._make_thesis()
        with self.assertRaises(ValidationError):
            self._make_thesis()
        first.action_cancel()
        second = self._make_thesis()
        self.assertEqual(second.state, 'draft')

    def test_supervisors_must_be_lecturers_and_distinct(self):
        self._record_metopen_grade(self.student, score=82.0)
        staff_emp = self.env['hr.employee'].create({
            'name': '%s Staf Biasa' % TAG,
            'academic_role': 'academic',
        })
        with self.assertRaises(ValidationError):
            self._make_thesis(supervisor_id=staff_emp.id)
        with self.assertRaises(ValidationError):
            self._make_thesis(co_supervisor_id=self.supervisor_emp.id)

    def test_single_supervisor_approval_and_role_guard(self):
        self._record_metopen_grade(self.student, score=85.0)
        thesis = self._make_thesis()
        thesis.action_submit_supervisor()
        self.assertEqual(thesis.state, 'supervisor_approval')

        with self.assertRaises(AccessError):
            thesis.with_user(self.other_lecturer_user).action_supervisor_approve()

        thesis.with_user(self.supervisor_user).action_supervisor_approve()
        self.assertTrue(thesis.supervisor_approved)
        self.assertEqual(thesis.state, 'proposal')

    def test_dual_supervisors_require_both_approvals(self):
        self._record_metopen_grade(self.student, score=85.0)
        thesis = self._make_thesis(co_supervisor=True)
        thesis.action_submit_supervisor()

        thesis.with_user(self.supervisor_user).action_supervisor_approve()
        self.assertTrue(thesis.supervisor_approved)
        self.assertFalse(thesis.co_supervisor_approved)
        self.assertEqual(thesis.state, 'supervisor_approval')

        thesis.with_user(self.co_supervisor_user).action_supervisor_approve()
        self.assertTrue(thesis.co_supervisor_approved)
        self.assertEqual(thesis.state, 'proposal')

    def test_supervisor_rejection_and_resubmission_with_new_supervisor(self):
        self._record_metopen_grade(self.student, score=85.0)
        thesis = self._make_thesis()
        thesis.action_submit_supervisor()

        thesis.with_user(self.supervisor_user).action_supervisor_reject(
            reason='Kuota bimbingan penuh',
        )
        self.assertEqual(thesis.state, 'supervisor_rejected')
        self.assertEqual(thesis.rejection_reason, 'Kuota bimbingan penuh')

        thesis.action_reset_to_draft()
        self.assertEqual(thesis.state, 'draft')
        thesis.write({'supervisor_id': self.co_supervisor_emp.id})
        thesis.action_submit_supervisor()
        thesis.with_user(self.co_supervisor_user).action_supervisor_approve()
        self.assertEqual(thesis.state, 'proposal')

    def test_proposal_progress_logs_and_permissions(self):
        self._record_metopen_grade(self.student, score=85.0)
        thesis = self._make_thesis()
        thesis.action_submit_supervisor()
        thesis.with_user(self.supervisor_user).action_supervisor_approve()

        log = self.env['campus.thesis.progress'].create({
            'thesis_id': thesis.id,
            'stage': 'proposal',
            'milestone': 'Bab I - Pendahuluan',
            'description': 'Draft rumusan masalah dan tujuan',
            'progress_percent': 45.0,
        })
        self.assertEqual(thesis.proposal_progress, 0.0)

        with self.assertRaises(AccessError):
            log.with_user(self.other_lecturer_user).action_approve()

        log.with_user(self.supervisor_user).action_approve()
        self.assertEqual(log.state, 'approved')
        self.assertEqual(thesis.proposal_progress, 45.0)

        # Cannot log thesis-stage progress while still in proposal stage
        with self.assertRaises(ValidationError):
            self.env['campus.thesis.progress'].create({
                'thesis_id': thesis.id,
                'stage': 'thesis',
                'milestone': 'Bab IV',
                'description': 'Belum tahap skripsi',
                'progress_percent': 10.0,
            })

    def test_thesis_stage_requires_approved_thesis_krs(self):
        self._record_metopen_grade(self.student, score=85.0)
        thesis = self._make_thesis()
        thesis.action_submit_supervisor()
        thesis.with_user(self.supervisor_user).action_supervisor_approve()

        # Without MK Skripsi in KRS -> lands on proposal_approved
        thesis.with_user(self.supervisor_user).action_approve_proposal()
        self.assertEqual(thesis.state, 'proposal_approved')

        with self.assertRaises(ValidationError):
            thesis.action_start_thesis()

        # Draft/submitted KRS is NOT enough
        krs = self._enroll_thesis_krs(self.student, approve=False)
        krs.action_submit()
        with self.assertRaises(ValidationError):
            thesis.action_start_thesis()

        # Once advisor approves the KRS -> Thesis stage unlocks
        krs.with_user(self.advisor_user).action_approve()
        self.assertTrue(thesis.thesis_course_enrolled)
        thesis.action_start_thesis()
        self.assertEqual(thesis.state, 'thesis')

    def test_proposal_advances_directly_when_thesis_krs_already_approved(self):
        self._record_metopen_grade(self.student, score=85.0)
        self._enroll_thesis_krs(self.student, approve=True)
        thesis = self._make_thesis()
        thesis.action_submit_supervisor()
        thesis.with_user(self.supervisor_user).action_supervisor_approve()
        thesis.with_user(self.supervisor_user).action_approve_proposal()
        self.assertEqual(thesis.state, 'thesis')

    def test_direct_state_write_bypass_is_blocked(self):
        self._record_metopen_grade(self.student, score=85.0)
        thesis = self._make_thesis()
        with self.assertRaises(ValidationError):
            thesis.write({'state': 'thesis'})
        with self.assertRaises(ValidationError):
            thesis.write({'state': 'graduated'})

    def test_sequential_yudisium_and_nearest_graduation_assignment(self):
        today = fields.Date.context_today(self.env.user)
        Schedule = self.env['campus.graduation.schedule']
        # Past schedule -> ignored
        Schedule.create({
            'name': '%s Wisuda Lalu' % TAG,
            'graduation_date': today - timedelta(days=5),
        })
        # Deadline already passed -> ignored
        Schedule.create({
            'name': '%s Wisuda Tutup Daftar' % TAG,
            'graduation_date': today + timedelta(days=10),
            'registration_deadline': today - timedelta(days=1),
        })
        # Nearest valid open schedule -> MUST win
        nearest_sched = Schedule.create({
            'name': '%s Wisuda Terdekat' % TAG,
            'graduation_date': today + timedelta(days=30),
            'registration_deadline': today + timedelta(days=20),
            'location': 'Graha Rektorat',
            'quota': 50,
        })
        # Farther valid schedule -> NOT selected
        Schedule.create({
            'name': '%s Wisuda Berikutnya' % TAG,
            'graduation_date': today + timedelta(days=120),
            'registration_deadline': today + timedelta(days=100),
        })

        self._record_metopen_grade(self.student, score=88.0)
        self._enroll_thesis_krs(self.student, approve=True)
        thesis = self._make_thesis()
        thesis.action_submit_supervisor()
        thesis.with_user(self.supervisor_user).action_supervisor_approve()
        thesis.with_user(self.supervisor_user).action_approve_proposal()
        self.assertEqual(thesis.state, 'thesis')

        thesis.with_user(self.supervisor_user).action_approve_thesis()
        self.assertEqual(thesis.state, 'yudisium_docs')
        self.assertTrue(thesis.yudisium_document_ids)

        # Incomplete documents cannot submit Yudisium
        with self.assertRaises(UserError):
            thesis.action_submit_yudisium()

        thesis.yudisium_document_ids.write({'received': True})
        self.assertTrue(thesis.documents_complete)
        thesis.action_submit_yudisium()
        self.assertEqual(thesis.state, 'yudisium_supervisor')

        # Step 1: Only Supervisor may approve
        with self.assertRaises(AccessError):
            thesis.with_user(self.advisor_user).action_yudisium_approve_supervisor()
        with self.assertRaises(UserError):
            thesis.with_user(self.advisor_user).action_yudisium_approve_advisor()
        thesis.with_user(self.supervisor_user).action_yudisium_approve_supervisor()
        self.assertEqual(thesis.state, 'yudisium_advisor')
        self.assertTrue(thesis.yudisium_supervisor_approved)

        # Return to docs clears sequential approvals cleanly
        thesis.with_user(self.advisor_user).action_yudisium_return_to_docs(reason='Perbaiki transkrip')
        self.assertEqual(thesis.state, 'yudisium_docs')
        self.assertFalse(thesis.yudisium_supervisor_approved)

        # Re-run sequential approvals: Supervisor -> Advisor -> Dean
        thesis.action_submit_yudisium()
        thesis.with_user(self.supervisor_user).action_yudisium_approve_supervisor()

        with self.assertRaises(AccessError):
            thesis.with_user(self.dean_user).action_yudisium_approve_advisor()
        thesis.with_user(self.advisor_user).action_yudisium_approve_advisor()
        self.assertEqual(thesis.state, 'yudisium_dean')
        self.assertTrue(thesis.yudisium_advisor_approved)

        with self.assertRaises(AccessError):
            thesis.with_user(self.supervisor_user).action_yudisium_approve_dean()
        thesis.with_user(self.dean_user).action_yudisium_approve_dean()

        self.assertEqual(thesis.state, 'graduated')
        self.assertTrue(thesis.yudisium_dean_approved)
        self.assertEqual(thesis.graduation_id, nearest_sched)
        self.assertEqual(self.student.student_status, 'graduated')

    def test_lecturer_move_guard_blocks_active_thesis_supervisor(self):
        self._record_metopen_grade(self.student, score=88.0)
        self._enroll_thesis_krs(self.student, approve=True)
        thesis = self._make_thesis()
        thesis.action_submit_supervisor()

        other_program = self.env['academic.program'].create({
            'name': '%s Sistem Komputer' % TAG,
            'code': 'ZSK',
            'faculty_id': self.faculty.id,
        })
        with self.assertRaises(ValidationError):
            self.supervisor_emp.write({'program_id': other_program.id})

        thesis.action_cancel()
        self.supervisor_emp.write({'program_id': other_program.id})
        self.assertEqual(self.supervisor_emp.program_id, other_program)
