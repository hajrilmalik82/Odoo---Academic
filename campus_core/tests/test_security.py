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
