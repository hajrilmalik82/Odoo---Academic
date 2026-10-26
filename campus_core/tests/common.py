from datetime import timedelta

from odoo import fields
from odoo.tests.common import HttpCase, TransactionCase

# Every record this fixture creates carries this marker in its name or code.
#
# A test must not assume an empty database. Several models here enforce
# uniqueness - academic.faculty and academic.program on lower(name),
# campus.building on code, academic.subject on code - so a fixture that used
# plausible campus names ("Teknik Informatika", "Gedung A") collided with the
# real master data of any database it ran against and every test errored in
# setUpClass before a single assertion ran.
#
# The marker is deliberately not something a campus would ever type.
TAG = 'ZZTEST'


class CampusFixture:
    """Builds the campus. Mixed into both test bases below.

    A plain mixin rather than a base class, so the same fixture serves a
    TransactionCase (model-level tests) and an HttpCase (routes and rendered
    pages) without being written twice.

    Shared fixture: one faculty, one programme, two subjects, one class.

    Built in setUpClass so every test starts from the same known campus rather
    than from whatever happens to be in the database. Everything is rolled back
    when the class finishes, so the host database is left untouched.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.faculty = cls.env['academic.faculty'].create({
            'name': '%s Fakultas Teknik' % TAG,
            'code': 'ZFT',
        })
        cls.program = cls.env['academic.program'].create({
            'name': '%s Teknik Informatika' % TAG,
            'code': 'ZIF',
            'faculty_id': cls.faculty.id,
        })

        today = fields.Date.context_today(cls.env.user)
        cls.year = cls.env['academic.year'].create({
            'name': '%s 2025/2026' % TAG,
            'term_type': 'odd',
            'krs_start_date': today - timedelta(days=1),
            'krs_end_date': today + timedelta(days=30),
        })
        cls.year_next = cls.env['academic.year'].create({
            'name': '%s 2026/2027' % TAG,
            'term_type': 'odd',
            'krs_start_date': today + timedelta(days=200),
            'krs_end_date': today + timedelta(days=230),
        })

        # A third year, also open, for scenarios that need a SECOND locked study
        # plan - repeating a subject, for instance. year_next stays closed on
        # purpose: two tests rely on it having no approved KRS.
        cls.year_retake = cls.env['academic.year'].create({
            'name': '%s 2027/2028' % TAG,
            'term_type': 'odd',
            'krs_start_date': today - timedelta(days=1),
            'krs_end_date': today + timedelta(days=30),
        })

        cls.subject_a = cls.env['academic.subject'].create({
            'name': '%s Algoritma' % TAG, 'code': 'ZIF101',
            'credits': 3, 'term_type': 'odd', 'program_id': cls.program.id,
        })
        cls.subject_b = cls.env['academic.subject'].create({
            'name': '%s Struktur Data' % TAG, 'code': 'ZIF102',
            'credits': 4, 'term_type': 'odd', 'program_id': cls.program.id,
        })

        cls.building = cls.env['campus.building'].create({
            'name': '%s Gedung A' % TAG, 'code': 'ZZA', 'location': 'Kampus Uji',
        })
        cls.room = cls.env['campus.room'].create({
            'name': '%s A-101' % TAG, 'building_id': cls.building.id,
            'capacity': 2, 'room_type': 'theory',
        })

        cls.klass = cls.env['academic.class'].create({
            'subject_id': cls.subject_a.id,
            'academic_year_id': cls.year.id,
            'start_date': today,
        })
        cls.schedule = cls.env['academic.class.schedule'].create({
            'class_id': cls.klass.id, 'class_code': 'A',
            'day_of_week': '0', 'start_time': 8.0, 'end_time': 10.0,
            'room_id': cls.room.id,
        })

        # academic_role matters: linking a user to an employee runs
        # _sync_academic_user_role, and an employee with no role holds no campus
        # group - so assigning a user to a role-less employee REVOKES that user's
        # lecturer group. An academic advisor is a lecturer, so say so.
        cls.klass_retake = cls.env['academic.class'].create({
            'subject_id': cls.subject_a.id,
            'academic_year_id': cls.year_retake.id,
            'start_date': today,
        })
        cls.schedule_retake = cls.env['academic.class.schedule'].create({
            'class_id': cls.klass_retake.id, 'class_code': 'A',
            'day_of_week': '0', 'start_time': 8.0, 'end_time': 10.0,
            'room_id': cls.room.id,
        })

        cls.advisor = cls.env['hr.employee'].create({
            'name': '%s Dosen PA' % TAG,
            'academic_role': 'lecturer',
        })
        cls.student = cls.env['res.partner'].create({
            'name': '%s Budi Santoso' % TAG,
            'is_student': True,
            'student_status': 'active',
            'program_id': cls.program.id,
            'academic_advisor_id': cls.advisor.id,
        })

    def _make_krs(self, student=None, year=None, schedules=None):
        """A draft KRS with one line per given schedule."""
        student = student or self.student
        year = year or self.year
        schedules = self.schedule if schedules is None else schedules
        return self.env['academic.krs'].create({
            'student_id': student.id,
            'academic_year_id': year.id,
            'line_ids': [
                (0, 0, {'schedule_id': schedule.id}) for schedule in schedules
            ],
        })


class CampusCommon(CampusFixture, TransactionCase):
    """Model-level tests: call the methods directly, no HTTP involved."""


class CampusHttpCommon(CampusFixture, HttpCase):
    """Route-level tests: a real server, real requests, real rendering.

    What a TransactionCase cannot reach - routing and its methods, CSRF, the
    auth decorator, QWeb rendering, and which language a frontend page is
    served in - only shows up here.

    Adds the two accounts the routes need. Passwords are set on the fixture's
    own users and never leave this database.
    """

    PORTAL_PASSWORD = 'zz-portal-password'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student_user = cls.env['res.users'].create({
            'name': cls.student.name,
            'login': 'zz.mahasiswa.http@contoh.test',
            'password': cls.PORTAL_PASSWORD,
            'partner_id': cls.student.id,
            'group_ids': [(6, 0, [cls.env.ref('base.group_portal').id])],
        })
        # An internal user with no campus role: the one whose /my/home used to
        # break because the counters raised AccessError.
        cls.outsider_user = cls.env['res.users'].create({
            'name': '%s Karyawan Biasa' % TAG,
            'login': 'zz.karyawan.http@contoh.test',
            'password': cls.PORTAL_PASSWORD,
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def sign_in_as_student(self):
        self.authenticate(self.student_user.login, self.PORTAL_PASSWORD)

    def sign_in_as_outsider(self):
        self.authenticate(self.outsider_user.login, self.PORTAL_PASSWORD)
