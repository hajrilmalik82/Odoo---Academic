from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class CampusCommon(TransactionCase):
    """Shared fixture: one faculty, one programme, two subjects, one class.

    Built in setUpClass so every test starts from the same known campus rather
    than from whatever happens to be in the database.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.faculty = cls.env['academic.faculty'].create({'name': 'Fakultas Teknik'})
        cls.program = cls.env['academic.program'].create({
            'name': 'Teknik Informatika',
            'faculty_id': cls.faculty.id,
        })

        today = fields.Date.context_today(cls.env.user)
        cls.year = cls.env['academic.year'].create({
            'name': '2025/2026',
            'term_type': 'odd',
            'krs_start_date': today - timedelta(days=1),
            'krs_end_date': today + timedelta(days=30),
        })
        cls.year_next = cls.env['academic.year'].create({
            'name': '2026/2027',
            'term_type': 'odd',
            'krs_start_date': today + timedelta(days=200),
            'krs_end_date': today + timedelta(days=230),
        })

        cls.subject_a = cls.env['academic.subject'].create({
            'name': 'Algoritma', 'code': 'IF101',
            'credits': 3, 'term_type': 'odd', 'program_id': cls.program.id,
        })
        cls.subject_b = cls.env['academic.subject'].create({
            'name': 'Struktur Data', 'code': 'IF102',
            'credits': 4, 'term_type': 'odd', 'program_id': cls.program.id,
        })

        cls.building = cls.env['campus.building'].create({
            'name': 'Gedung A', 'code': 'A', 'location': 'Kampus Utama',
        })
        cls.room = cls.env['campus.room'].create({
            'name': 'A-101', 'building_id': cls.building.id,
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

        cls.advisor = cls.env['hr.employee'].create({'name': 'Dosen PA'})
        cls.student = cls.env['res.partner'].create({
            'name': 'Budi Santoso',
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
