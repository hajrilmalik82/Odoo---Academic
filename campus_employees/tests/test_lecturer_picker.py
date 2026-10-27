from datetime import timedelta

from odoo import fields
from odoo.tests.common import tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.campus_core.tests.common import TAG, CampusCommon


@tagged('post_install', '-at_install')
class TestLecturerPicker(CampusCommon):
    """Who the Lecturer field offers, on the weekly schedule and on a session.

    The rule is deliberately looser than the one on dean_id and head_id: a
    lecturer of the subject's programme OR of its faculty. Teaching across
    programmes inside your own faculty is ordinary; heading somebody else's
    programme is not.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # A second programme in the SAME faculty, which is what makes the OR
        # branch of the domain observable at all.
        cls.sibling_program = cls.env['academic.program'].create({
            'name': '%s Sistem Informasi' % TAG,
            'code': 'ZSI',
            'faculty_id': cls.faculty.id,
        })
        cls.far_faculty = cls.env['academic.faculty'].create({
            'name': '%s Fakultas Jauh' % TAG,
            'code': 'ZFJ',
        })
        cls.far_program = cls.env['academic.program'].create({
            'name': '%s Program Jauh' % TAG,
            'code': 'ZPJ',
            'faculty_id': cls.far_faculty.id,
        })

        cls.own_lecturer = cls.env['hr.employee'].create({
            'name': '%s Dosen Prodi' % TAG,
            'academic_role': 'lecturer',
            'faculty_id': cls.faculty.id,
            'program_id': cls.program.id,
        })
        cls.faculty_peer = cls.env['hr.employee'].create({
            'name': '%s Dosen Satu Fakultas' % TAG,
            'academic_role': 'lecturer',
            'faculty_id': cls.faculty.id,
            'program_id': cls.sibling_program.id,
        })
        cls.far_lecturer = cls.env['hr.employee'].create({
            'name': '%s Dosen Fakultas Jauh' % TAG,
            'academic_role': 'lecturer',
            'faculty_id': cls.far_faculty.id,
            'program_id': cls.far_program.id,
        })
        cls.staff = cls.env['hr.employee'].create({
            'name': '%s Staf TU Kelas' % TAG,
            'academic_role': 'academic',
            'faculty_id': cls.faculty.id,
            'program_id': cls.program.id,
        })

        start = fields.Datetime.now()
        cls.session = cls.env['academic.class.session'].create({
            'name': '%s Pertemuan 1' % TAG,
            'class_id': cls.klass.id,
            'start_datetime': start,
            'end_datetime': start + timedelta(hours=2),
        })

    def _candidates(self, record):
        """What the picker would offer on this record: its own field domain,
        evaluated against the record the way a form view evaluates it."""
        domain = safe_eval(record._fields['lecturer_id'].domain, {
            'class_program_id': record.class_program_id.id,
            'class_faculty_id': record.class_faculty_id.id,
        })
        return self.env['hr.employee'].search(domain)

    # --- the rule ---------------------------------------------------------

    def test_a_session_offers_lecturers_of_the_programme(self):
        self.assertIn(self.own_lecturer, self._candidates(self.session))

    def test_a_session_offers_lecturers_of_the_faculty(self):
        """The OR branch: another programme, same faculty, still allowed."""
        self.assertIn(self.faculty_peer, self._candidates(self.session))

    def test_a_session_refuses_a_lecturer_from_another_faculty(self):
        self.assertNotIn(self.far_lecturer, self._candidates(self.session))

    def test_a_session_refuses_somebody_who_is_not_a_lecturer(self):
        self.assertNotIn(self.staff, self._candidates(self.session))

    def test_a_session_refuses_an_employee_with_no_academic_profile(self):
        """Odoo's own demo staff are exactly this: employees with no academic
        role at all. This is the case the session form used to offer."""
        plain = self.env['hr.employee'].create({'name': '%s Pegawai Biasa' % TAG})
        self.assertNotIn(plain, self._candidates(self.session))

    def test_the_schedule_applies_the_same_rule(self):
        candidates = self._candidates(self.schedule)
        self.assertIn(self.own_lecturer, candidates)
        self.assertIn(self.faculty_peer, candidates)
        self.assertNotIn(self.far_lecturer, candidates)

    def test_the_two_models_share_one_domain(self):
        """Declared once in campus_employees and reused, so a change to one
        cannot leave the other behind."""
        self.assertEqual(
            self.env['academic.class.schedule']._fields['lecturer_id'].domain,
            self.env['academic.class.session']._fields['lecturer_id'].domain,
        )

    # --- the wiring the rule depends on -----------------------------------

    def test_the_class_relation_resolves_the_programme_and_faculty(self):
        """The domain is worthless if these come back empty: it then reads as
        ('program_id', '=', False) and offers lecturers who have no programme."""
        self.assertEqual(self.session.class_program_id, self.program)
        self.assertEqual(self.session.class_faculty_id, self.faculty)

    def test_every_view_that_picks_a_lecturer_carries_what_the_domain_reads(self):
        """A dynamic domain is evaluated by the client against the form, so a
        field it names must be present there - invisible is enough, absent is
        not. Absent raises nothing: the domain quietly stops narrowing.

        The three views are named rather than discovered. A fourth place to pick
        a lecturer would not be caught here, and would have to be added.
        """
        views = [
            ('academic.class.session', 'campus_core.view_academic_class_session_form', 'form'),
            ('academic.class.schedule', 'campus_core.view_academic_class_schedule_form', 'form'),
            ('academic.class', 'campus_core.view_academic_class_form', 'form'),
        ]
        for model, xmlid, view_type in views:
            with self.subTest(view=xmlid):
                arch = self.env[model].get_view(self.env.ref(xmlid).id, view_type)['arch']
                self.assertIn('class_program_id', arch)
                self.assertIn('class_faculty_id', arch)
