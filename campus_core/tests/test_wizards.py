from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .common import TAG, CampusCommon


@tagged('post_install', '-at_install')
class TestKrsGeneratorWizard(CampusCommon):
    """Opens a study plan for a whole cohort from a course package."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.package = cls.env['academic.course.package'].create({
            'name': '%s Paket Semester 1' % TAG,
            'program_id': cls.program.id,
            'academic_year_id': cls.year.id,
            'line_ids': [
                (0, 0, {'subject_id': cls.subject_a.id}),
                (0, 0, {'subject_id': cls.subject_b.id}),
            ],
        })

    def _wizard(self, students):
        return self.env['krs.generator.wizard'].create({
            'package_id': self.package.id,
            'student_ids': [(6, 0, students.ids)],
        })

    def test_it_opens_a_plan_for_each_student(self):
        second = self.env['res.partner'].create({
            'name': '%s Mahasiswa Paket' % TAG, 'is_student': True,
            'student_status': 'active', 'program_id': self.program.id,
            'academic_advisor_id': self.advisor.id,
        })
        students = self.student | second
        self._wizard(students).action_generate_krs()

        plans = self.env['academic.krs'].search([
            ('student_id', 'in', students.ids),
            ('academic_year_id', '=', self.year.id),
        ])
        self.assertEqual(len(plans), 2)
        for plan in plans:
            self.assertEqual(plan.state, 'draft')
            self.assertEqual(
                set(plan.line_ids.mapped('subject_id').ids),
                {self.subject_a.id, self.subject_b.id},
            )

    def test_the_package_decides_the_programme_and_faculty(self):
        self._wizard(self.student).action_generate_krs()
        plan = self.env['academic.krs'].search([
            ('student_id', '=', self.student.id), ('academic_year_id', '=', self.year.id),
        ])
        self.assertEqual(plan.program_id, self.program)
        self.assertEqual(plan.faculty_id, self.faculty)

    def test_a_student_is_never_given_two_plans_for_one_term(self):
        """academic.krs carries a UNIQUE on (student, year), so a second run
        would be a database error rather than a message."""
        self._wizard(self.student).action_generate_krs()
        with self.assertRaises(ValidationError):
            self._wizard(self.student).action_generate_krs()

    def test_it_refuses_an_empty_selection(self):
        wizard = self.env['krs.generator.wizard'].create({'package_id': self.package.id})
        with self.assertRaises(ValidationError):
            wizard.action_generate_krs()


@tagged('post_install', '-at_install')
class TestAssignScheduleWizard(CampusCommon):
    """Puts a whole class's worth of students into one section at once.

    The seat check here is the one that had to learn about draft plans: the
    wizard writes schedule_id onto DRAFT lines, so counting only submitted
    plans meant a second run could not see its own first one.
    """

    def _student(self, suffix):
        return self.env['res.partner'].create({
            'name': '%s Mahasiswa %s' % (TAG, suffix), 'is_student': True,
            'student_status': 'active', 'program_id': self.program.id,
            'academic_advisor_id': self.advisor.id,
        })

    def _unscheduled_line(self, student):
        """A KRS line that names a subject but has no section yet."""
        krs = self.env['academic.krs'].create({
            'student_id': student.id,
            'academic_year_id': self.year.id,
            'line_ids': [(0, 0, {'subject_id': self.subject_a.id})],
        })
        return krs.line_ids

    def _wizard(self, lines):
        return self.env['assign.schedule.wizard'].create({
            'class_id': self.klass.id,
            'schedule_id': self.schedule.id,
            'krs_line_ids': [(6, 0, lines.ids)],
        })

    def test_it_assigns_the_section_to_every_selected_line(self):
        lines = self._unscheduled_line(self.student) | self._unscheduled_line(self._student('W2'))
        self._wizard(lines).action_assign_schedule()
        self.assertEqual(set(lines.mapped('schedule_id').ids), {self.schedule.id})

    def test_it_refuses_more_students_than_the_room_holds(self):
        """The fixture room seats two."""
        self.assertEqual(self.schedule.room_capacity, 2)
        lines = self.env['academic.krs.line']
        for suffix in ('W3', 'W4', 'W5'):
            lines |= self._unscheduled_line(self._student(suffix))
        with self.assertRaises(ValidationError):
            self._wizard(lines).action_assign_schedule()

    def test_a_second_run_sees_what_the_first_one_placed(self):
        """Draft plans hold a seat as far as this wizard is concerned. Counting
        only submitted plans let the same room be filled twice over."""
        first = self._unscheduled_line(self._student('W6')) | self._unscheduled_line(self._student('W7'))
        self._wizard(first).action_assign_schedule()
        self.assertEqual(
            self.schedule._enrolled_count(
                states=self.env['academic.krs']._EDITABLE_STATES
                       + self.schedule._ENROLLED_KRS_STATES,
            ),
            2,
        )
        overflow = self._unscheduled_line(self._student('W8'))
        with self.assertRaises(ValidationError):
            self._wizard(overflow).action_assign_schedule()

    def test_it_refuses_a_line_from_another_subject(self):
        krs = self.env['academic.krs'].create({
            'student_id': self._student('W9').id,
            'academic_year_id': self.year.id,
            'line_ids': [(0, 0, {'subject_id': self.subject_b.id})],
        })
        with self.assertRaises(ValidationError):
            self._wizard(krs.line_ids).action_assign_schedule()

    def test_it_refuses_a_line_that_already_has_a_section(self):
        """Reassigning is not this wizard's job: it fills empty lines.

        The state check further down the method is unreachable through the real
        flow - a plan cannot be submitted while any line lacks a section, so a
        line that is both unscheduled and past draft does not exist - and this
        is the refusal a user actually meets.
        """
        line = self._unscheduled_line(self._student('W10'))
        line.schedule_id = self.schedule
        with self.assertRaises(ValidationError):
            self._wizard(line).action_assign_schedule()
