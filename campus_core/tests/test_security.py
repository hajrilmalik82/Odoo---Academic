from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import tagged

from .common import CampusCommon


@tagged('post_install', '-at_install')
class TestCampusSecurity(CampusCommon):
    """Who may see and change what. Each test pins one hole the audit found."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lecturer_group = cls.env.ref('campus_core.group_campus_lecturer')
        cls.admin_group = cls.env.ref('campus_core.group_campus_administrator')
        cls.internal_group = cls.env.ref('base.group_user')

        cls.lecturer_user = cls.env['res.users'].create({
            'name': 'Dosen Lain', 'login': 'dosen.lain.test',
            'group_ids': [(6, 0, [cls.internal_group.id, cls.lecturer_group.id])],
        })
        cls.portal_user = cls.env['res.users'].create({
            'name': 'Budi Santoso', 'login': 'budi.test',
            'partner_id': cls.student.id,
            'group_ids': [(6, 0, [cls.env.ref('base.group_portal').id])],
        })

    def test_portal_cannot_write_its_own_krs(self):
        """Read-only by ACL: the portal controller mutates with sudo instead.

        While portal users held write access they could call write({'state':
        'submitted'}) over /web/dataset/call_kw and skip every submission rule.
        """
        krs = self._make_krs()
        self.assertTrue(krs.with_user(self.portal_user).has_access('read'))
        self.assertFalse(krs.with_user(self.portal_user).has_access('write'))
        with self.assertRaises(AccessError):
            krs.with_user(self.portal_user).write({'state': 'submitted'})

    def test_portal_sees_only_its_own_krs(self):
        other_student = self.env['res.partner'].create({
            'name': 'Citra', 'is_student': True, 'student_status': 'active',
            'program_id': self.program.id,
        })
        mine = self._make_krs()
        self._make_krs(student=other_student)
        visible = self.env['academic.krs'].with_user(self.portal_user).search([])
        self.assertEqual(visible, mine)

    def test_lecturer_sees_only_their_own_advisees(self):
        """A lecturer used to read and write every KRS in the university."""
        krs = self._make_krs()
        visible = self.env['academic.krs'].with_user(self.lecturer_user).search([])
        self.assertNotIn(krs, visible, "not this lecturer's advisee")

        self.advisor.user_id = self.lecturer_user
        self.student.invalidate_recordset()
        visible = self.env['academic.krs'].with_user(self.lecturer_user).search([])
        self.assertIn(krs, visible, "their own advisee must be visible")

    def test_administrator_sees_every_grade_line(self):
        """group_campus_administrator implies the lecturer group, so without an
        admin rule of its own the lecturer rule narrowed administrators to the
        classes they personally teach, which is usually none."""
        krs = self._make_krs()
        krs.action_submit()
        krs.action_approve()
        krs.action_lock()
        admin = self.env.ref('base.user_admin')
        total = self.env['academic.khs.line'].sudo().search_count([])
        visible = self.env['academic.khs.line'].with_user(admin).search_count([])
        self.assertEqual(visible, total)

    def test_lecturer_cannot_edit_arbitrary_contacts(self):
        vendor = self.env['res.partner'].create({'name': 'Vendor ATK'})
        self.assertFalse(vendor.with_user(self.lecturer_user).has_access('write'))

    def test_academic_staff_cannot_delete_contacts(self):
        staff_user = self.env['res.users'].create({
            'name': 'Staf TU', 'login': 'staf.tu.test',
            'group_ids': [(6, 0, [
                self.internal_group.id,
                self.env.ref('campus_core.group_campus_academic_staff').id,
            ])],
        })
        vendor = self.env['res.partner'].create({'name': 'Vendor ATK'})
        self.assertFalse(vendor.with_user(staff_user).has_access('unlink'))

    def test_prerequisite_cycle_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.subject_a.prerequisite_ids = self.subject_a

    def test_non_advisor_lecturer_cannot_reject_or_request_revision(self):
        other_lecturer_user = self.env['res.users'].create({
            'name': 'Dosen Penguji', 'login': 'dosen.penguji.test',
            'group_ids': [(6, 0, [self.internal_group.id, self.lecturer_group.id])],
        })
        self.advisor.user_id = self.lecturer_user
        krs = self._make_krs()
        krs.action_submit()
        with self.assertRaises(AccessError):
            krs.with_user(other_lecturer_user).action_request_revision()
        with self.assertRaises(AccessError):
            krs.with_user(other_lecturer_user).action_reject()
        with self.assertRaises(AccessError):
            krs.with_user(other_lecturer_user).write({'state': 'rejected'})

    def test_advisor_can_read_advisee_khs_lines_not_write(self):
        self.advisor.user_id = self.lecturer_user
        krs = self._make_krs()
        krs.action_submit()
        krs.action_approve()
        krs.action_lock()
        khs_lines = self.env['academic.khs.line'].with_user(self.lecturer_user).search([
            ('khs_id.student_id', '=', self.student.id),
        ])
        self.assertEqual(len(khs_lines), 1)
        with self.assertRaises(AccessError):
            khs_lines.with_user(self.lecturer_user).write({'numeric_grade': 95.0})

    def test_teaching_lecturer_can_grade_via_khs_form_and_not_edit_header(self):
        self.schedule.lecturer_id = self.advisor
        self.advisor.user_id = self.lecturer_user
        krs = self._make_krs()
        krs.action_submit()
        krs.action_approve()
        krs.action_lock()
        khs = self.env['academic.khs'].with_user(self.lecturer_user).search([
            ('student_id', '=', self.student.id),
            ('academic_year_id', '=', self.year.id),
        ], limit=1)
        self.assertTrue(khs)
        arch = khs.get_view(self.env.ref('campus_core.view_academic_khs_form').id, 'form')['arch']
        self.assertNotIn('edit="False"', arch)

        line = khs.line_ids[:1]
        khs.with_user(self.lecturer_user).write({'line_ids': [(1, line.id, {'numeric_grade': 85.0})]})
        self.assertEqual(line.numeric_grade, 85.0)
        self.assertTrue(line.is_graded)
        self.assertGreater(khs.term_gpa, 0.0)

        with self.assertRaises(AccessError):
            khs.with_user(self.lecturer_user).write({'name': 'HACK'})
        with self.assertRaises(AccessError):
            khs.with_user(self.lecturer_user).write({'line_ids': [(2, line.id)]})

    def test_lecturer_can_read_course_packages_and_cannot_spoof_khs_credits(self):
        package = self.env['academic.course.package'].create({
            'name': 'Paket Test ACL', 'program_id': self.program.id,
            'academic_year_id': self.year.id, 'semester': '1',
            'line_ids': [(0, 0, {'subject_id': self.subject_a.id})],
        })
        self.assertEqual(
            self.env['academic.course.package'].with_user(self.lecturer_user).search([('id', '=', package.id)]),
            package,
        )
        self.schedule.lecturer_id = self.advisor
        self.advisor.user_id = self.lecturer_user
        krs = self._make_krs()
        krs.action_submit()
        krs.action_approve()
        krs.action_lock()
        line = self.env['academic.khs.line'].search([('khs_id.student_id', '=', self.student.id)], limit=1)
        with self.assertRaises(AccessError):
            line.with_user(self.lecturer_user).write({'credits': 99})

    def test_krs_line_move_and_credit_override_guards(self):
        frozen_krs = self._make_krs()
        frozen_krs.action_submit()
        other_student = self.env['res.partner'].create({
            'name': 'Mahasiswa Lain KRS', 'is_student': True, 'student_status': 'active',
            'program_id': self.program.id, 'academic_advisor_id': self.advisor.id,
        })
        draft_krs = self.env['academic.krs'].create({
            'student_id': other_student.id, 'academic_year_id': self.year.id,
            'line_ids': [(0, 0, {'subject_id': self.subject_b.id})],
        })
        staff_user = self.env['res.users'].create({
            'name': 'Staf Guard', 'login': 'staf.guard.test',
            'group_ids': [(6, 0, [
                self.internal_group.id,
                self.env.ref('campus_core.group_campus_academic_staff').id,
            ])],
        })
        if 'campus.jurisdiction' in self.env:
            staff_emp = self.env['hr.employee'].create({
                'name': 'Staf Guard',
                'academic_role': 'academic',
                'user_id': staff_user.id,
            })
            self.env['campus.jurisdiction'].create({
                'employee_id': staff_emp.id,
                'scope': 'academic',
                'all_faculties': True,
                'all_programs': True,
            })
        with self.assertRaises(ValidationError):
            draft_krs.line_ids.with_user(staff_user).write({'krs_id': frozen_krs.id})
        with self.assertRaises(AccessError):
            draft_krs.line_ids.with_user(staff_user).write({'credits': 99})

    def test_plain_internal_user_can_open_student_and_company_contacts(self):
        """An internal user without campus roles must open Contacts without AccessError."""
        accountant = self.env['res.users'].create({
            'name': 'Akuntan Test', 'login': 'akuntan.sec.test',
            'group_ids': [(6, 0, [self.internal_group.id])],
        })
        company_contact = self.env['res.partner'].create({
            'name': 'PT Mitra Kampus', 'is_company': True,
        })
        for partner in (self.student, company_contact):
            with self.subTest(partner=partner.name):
                arch, values = self._open_form_as(
                    partner, accountant, 'base.view_partner_form',
                )
                self.assertEqual(values['name'], partner.name)
                self.assertNotIn('krs_count', arch)
                self.assertNotIn('khs_count', arch)
                self.assertNotIn('program_id', arch)
                self.assertEqual(partner.with_user(accountant).krs_count, 0)
                self.assertEqual(partner.with_user(accountant).khs_count, 0)
