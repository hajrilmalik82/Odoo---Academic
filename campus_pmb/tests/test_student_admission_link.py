from odoo.tests.common import tagged

from odoo.addons.campus_core.tests.common import TAG, CampusCommon


@tagged('post_install', '-at_install')
class TestStudentAdmissionLink(CampusCommon):
    """The Admissions counter on the student form.

    campus_core owns both student forms and knows nothing about admissions, so
    this counter is grafted on from campus_pmb. The graft is what these tests
    watch: a counter declared in one module and placed by another breaks
    quietly when either side moves.
    """

    def _admission(self, partner=None):
        return self.env['campus.admission'].create({
            'name': '%s Pendaftar' % TAG,
            'email': 'zz.tautan@contoh.test',
            'faculty_id': self.faculty.id,
            'program_id': self.program.id,
            'academic_year_id': self.year.id,
            'partner_id': (partner or self.student).id,
        })

    def test_a_student_with_no_admission_counts_zero(self):
        self.assertEqual(self.student.admission_count, 0)

    def test_the_counter_follows_the_admissions(self):
        self._admission()
        self.assertEqual(self.student.admission_count, 1)

    def test_the_button_opens_exactly_what_it_counted(self):
        admission = self._admission()
        action = self.student.action_open_admissions()
        self.assertEqual(action['res_model'], 'campus.admission')
        self.assertEqual(
            self.env['campus.admission'].search(action['domain']), admission)

    def test_an_admission_may_not_be_created_from_the_student(self):
        """An admission is where a student comes FROM: accepting one is what
        creates the contact. Making one from the contact inverts the order the
        NIM and the programme depend on."""
        self.assertFalse(self.student.action_open_admissions()['context'].get('create'))

    def test_both_student_forms_carry_the_admission_counter(self):
        """Grafted onto two views that another module owns. Either of them
        being rewritten would drop the button without any error."""
        views = (
            'campus_core.view_campus_student_form_standalone',
            'campus_core.view_partner_form_inherit_campus',
        )
        for xmlid in views:
            with self.subTest(view=xmlid):
                arch = self.env['res.partner'].get_view(
                    self.env.ref(xmlid).id, 'form')['arch']
                self.assertIn('admission_count', arch)
