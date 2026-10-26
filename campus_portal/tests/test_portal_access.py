from odoo.exceptions import AccessError
from odoo.tests.common import tagged

from odoo.addons.campus_core.tests.common import TAG, CampusCommon


@tagged('post_install', '-at_install')
class TestPortalAccess(CampusCommon):
    """What a student may reach through /my, and what everyone else may not.

    Every mutating route in this module runs with sudo, so the ownership checks
    are the only thing between a student and someone else's study plan.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        portal_group = cls.env.ref('base.group_portal')
        cls.student_user = cls.env['res.users'].create({
            'name': cls.student.name, 'login': 'zz.mhs.portal.test',
            'partner_id': cls.student.id,
            'group_ids': [(6, 0, [portal_group.id])],
        })
        cls.other_student = cls.env['res.partner'].create({
            'name': '%s Mahasiswa B' % TAG, 'is_student': True,
            'student_status': 'active', 'program_id': cls.program.id,
            'academic_advisor_id': cls.advisor.id,
        })
        # An internal user with no campus role at all - an accountant, say.
        cls.outsider = cls.env['res.users'].create({
            'name': '%s Karyawan Biasa' % TAG, 'login': 'zz.karyawan.test',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def test_the_home_counters_do_not_raise_for_an_internal_user(self):
        """/my/counters batches up to five counters per call and the client
        awaits it in willStart, so one AccessError left the whole batch's cards
        hidden and the portal spinner turning for ever - including cards owned
        by other modules."""
        partner = self.outsider.partner_id
        with self.assertRaises(AccessError):
            self.env['academic.krs'].with_user(self.outsider).search_count([])
        count = self.env['academic.krs'].with_user(self.outsider).sudo().search_count([
            ('student_id', '=', partner.id),
        ])
        self.assertEqual(count, 0)

    def test_the_counter_domain_is_pinned_to_the_caller(self):
        """sudo() is safe here only because the domain names the caller."""
        self._make_krs()
        own = self.env['academic.krs'].sudo().search_count([
            ('student_id', '=', self.student.id),
        ])
        theirs = self.env['academic.krs'].sudo().search_count([
            ('student_id', '=', self.other_student.id),
        ])
        self.assertEqual(own, 1)
        self.assertEqual(theirs, 0)

    def test_a_student_cannot_read_another_students_krs(self):
        mine = self._make_krs()
        theirs = self._make_krs(student=self.other_student, year=self.year_retake,
                                schedules=self.schedule_retake)
        visible = self.env['academic.krs'].with_user(self.student_user).search([])
        self.assertIn(mine, visible)
        self.assertNotIn(theirs, visible)

    def test_a_student_cannot_reach_another_students_krs_lines(self):
        """academic.krs.line carries its own student_id and state, so asking the
        child model answered exactly what the parent rule refuses."""
        theirs = self._make_krs(student=self.other_student, year=self.year_retake,
                                schedules=self.schedule_retake)
        visible = self.env['academic.krs.line'].with_user(self.student_user).search([])
        self.assertFalse(visible & theirs.line_ids)

    def test_a_student_has_no_write_access_of_their_own(self):
        """Read-only by ACL: the controller mutates with sudo after checking
        ownership, so write access would let a student skip every rule over
        /web/dataset/call_kw."""
        krs = self._make_krs()
        self.assertTrue(krs.with_user(self.student_user).has_access('read'))
        self.assertFalse(krs.with_user(self.student_user).has_access('write'))

    def test_pagination_is_not_taken_from_the_shared_portal_attribute(self):
        """CustomerPortal._items_per_page is shared by every module that
        subclasses it, so overriding it re-paginated sale, account and project."""
        from odoo.addons.portal.controllers.portal import CustomerPortal
        from odoo.addons.campus_portal.controllers.portal import (
            _CAMPUS_ITEMS_PER_PAGE, CampusPortal,
        )
        self.assertEqual(_CAMPUS_ITEMS_PER_PAGE, 20)
        self.assertEqual(CampusPortal._items_per_page, CustomerPortal._items_per_page)

    def test_the_register_route_only_accepts_post(self):
        """It creates a record, so as a GET it was reachable from any link or
        prefetch with no CSRF token involved."""
        from odoo.addons.campus_portal.controllers.portal import CampusPortal
        routing = CampusPortal.portal_my_krs_register.original_routing
        self.assertEqual(routing.get('methods'), ['POST'])
