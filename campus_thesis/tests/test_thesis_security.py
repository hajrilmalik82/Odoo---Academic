from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests.common import tagged

from odoo.addons.campus_core.tests.common import TAG, CampusCommon
from .test_thesis_workflow import ThesisFixtureMixin


@tagged('post_install', '-at_install')
class TestThesisSecurity(ThesisFixtureMixin, CampusCommon):
    """Record rules, ACLs, jurisdiction scoping, and anti-tampering guards."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_thesis_actors()
        today = fields.Date.context_today(cls.env.user)

        cls.other_faculty = cls.env['academic.faculty'].create({
            'name': '%s Fakultas Ekonomi' % TAG,
            'code': 'ZFE',
        })
        cls.other_program = cls.env['academic.program'].create({
            'name': '%s Manajemen' % TAG,
            'code': 'ZMN',
            'faculty_id': cls.other_faculty.id,
        })
        cls.other_metopen = cls.env['academic.subject'].create({
            'name': '%s Metodologi Bisnis' % TAG,
            'code': 'ZMB301',
            'credits': 3,
            'term_type': 'odd',
            'thesis_role': 'research_method',
            'program_id': cls.other_program.id,
        })
        cls.other_metopen_class = cls.env['academic.class'].create({
            'subject_id': cls.other_metopen.id,
            'academic_year_id': cls.year_retake.id,
            'start_date': today,
        })
        cls.other_metopen_schedule = cls.env['academic.class.schedule'].create({
            'class_id': cls.other_metopen_class.id,
            'class_code': 'A',
            'day_of_week': '5',
            'start_time': 10.0,
            'end_time': 12.0,
            'room_id': cls.thesis_room.id,
        })
        cls.other_supervisor = cls.env['hr.employee'].create({
            'name': '%s Dr. Dosen FE' % TAG,
            'academic_role': 'lecturer',
            'faculty_id': cls.other_faculty.id,
            'program_id': cls.other_program.id,
        })
        cls.other_student = cls.env['res.partner'].create({
            'name': '%s Sinta Dewi' % TAG,
            'is_student': True,
            'student_status': 'active',
            'program_id': cls.other_program.id,
        })

        # Pass metopen for both students via real KRS -> Lock -> KHS workflow
        for student, schedule in (
            (cls.student, cls.metopen_schedule),
            (cls.other_student, cls.other_metopen_schedule),
        ):
            krs = cls.env['academic.krs'].create({
                'student_id': student.id,
                'academic_year_id': cls.year_retake.id,
                'line_ids': [Command.create({'schedule_id': schedule.id})],
            })
            krs.action_submit()
            krs.action_approve()
            krs.action_lock()
            khs = cls.env['academic.khs'].search([
                ('student_id', '=', student.id),
                ('academic_year_id', '=', cls.year_retake.id),
            ], limit=1)
            khs.line_ids.write({'numeric_grade': 85.0, 'is_graded': True})

        cls.thesis_ft = cls.env['campus.thesis'].create({
            'student_id': cls.student.id,
            'academic_year_id': cls.year.id,
            'title': '%s Skripsi FT' % TAG,
            'supervisor_id': cls.supervisor_emp.id,
            'co_supervisor_id': cls.co_supervisor_emp.id,
        })
        cls.thesis_fe = cls.env['campus.thesis'].create({
            'student_id': cls.other_student.id,
            'academic_year_id': cls.year.id,
            'title': '%s Skripsi FE' % TAG,
            'supervisor_id': cls.other_supervisor.id,
        })

    def test_lecturer_visibility_scoped_to_role(self):
        # Supervisor, Co-Supervisor, Advisor, and Dean all see thesis_ft, not thesis_fe
        for actor in (self.supervisor_user, self.co_supervisor_user, self.advisor_user, self.dean_user):
            found = self.env['campus.thesis'].with_user(actor).search([
                ('id', 'in', [self.thesis_ft.id, self.thesis_fe.id]),
            ])
            self.assertEqual(found, self.thesis_ft)

        # Unrelated lecturer sees neither
        unrelated = self.env['campus.thesis'].with_user(self.other_lecturer_user).search([
            ('id', 'in', [self.thesis_ft.id, self.thesis_fe.id]),
        ])
        self.assertFalse(unrelated)

    def test_academic_staff_scoped_by_jurisdiction(self):
        base_group = self.env.ref('base.group_user')
        staff_user = self.env['res.users'].create({
            'name': '%s Staf TU FT' % TAG,
            'login': 'zz.tu.ft.thesis@contoh.test',
            'group_ids': [Command.set([base_group.id])],
        })
        staff_emp = self.env['hr.employee'].create({
            'name': '%s Staf FT' % TAG,
            'academic_role': 'academic',
            'faculty_id': self.faculty.id,
            'user_id': staff_user.id,
        })
        self.env['campus.jurisdiction'].create({
            'employee_id': staff_emp.id,
            'scope': 'academic',
            'faculty_ids': [Command.set([self.faculty.id])],
        })

        visible = self.env['campus.thesis'].with_user(staff_user).search([
            ('id', 'in', [self.thesis_ft.id, self.thesis_fe.id]),
        ])
        self.assertEqual(visible, self.thesis_ft)

    def test_campus_admin_sees_all_theses(self):
        admin_group = self.env.ref('campus_core.group_campus_administrator')
        admin_user = self.env['res.users'].create({
            'name': '%s Admin Thesis' % TAG,
            'login': 'zz.admin.thesis@contoh.test',
            'group_ids': [Command.set([admin_group.id])],
        })
        visible = self.env['campus.thesis'].with_user(admin_user).search([
            ('id', 'in', [self.thesis_ft.id, self.thesis_fe.id]),
        ])
        self.assertEqual(visible, self.thesis_ft | self.thesis_fe)

    def test_portal_student_read_only_own_thesis(self):
        portal_group = self.env.ref('base.group_portal')
        student_user = self.env['res.users'].create({
            'name': self.student.name,
            'login': 'zz.student.sec@contoh.test',
            'partner_id': self.student.id,
            'group_ids': [Command.set([portal_group.id])],
        })
        ThesisPortal = self.env['campus.thesis'].with_user(student_user)
        found = ThesisPortal.search([('id', 'in', [self.thesis_ft.id, self.thesis_fe.id])])
        self.assertEqual(found, self.thesis_ft)

        with self.assertRaises(AccessError):
            ThesisPortal.create({
                'student_id': self.student.id,
                'academic_year_id': self.year.id,
                'title': 'Direct Create Blocked',
                'supervisor_id': self.supervisor_emp.id,
            })
        with self.assertRaises(AccessError):
            self.thesis_ft.with_user(student_user).write({'title': 'Tampered'})

    def test_cannot_forge_approval_flags_directly(self):
        with self.assertRaises(AccessError):
            self.thesis_ft.with_user(self.supervisor_user).write({'yudisium_dean_approved': True})

    def test_lecturer_cannot_mark_yudisium_documents_received(self):
        self.thesis_ft._ensure_default_documents()
        doc = self.thesis_ft.yudisium_document_ids[:1]
        with self.assertRaises(AccessError):
            doc.with_user(self.supervisor_user).write({'received': True})

    def test_lecturer_cannot_cancel_thesis_or_edit_protected_snapshot_fields(self):
        with self.assertRaises(AccessError):
            self.thesis_ft.with_user(self.advisor_user).action_cancel()
        with self.assertRaises(AccessError):
            self.thesis_ft.with_user(self.supervisor_user).write({'program_id': self.other_program.id})
        with self.assertRaises(AccessError):
            self.thesis_ft.with_user(self.supervisor_user).write({'rejection_reason': 'forged'})

    def test_advisor_cannot_create_or_alter_progress_log_content(self):
        self.thesis_ft.action_submit_supervisor()
        self.thesis_ft.with_user(self.supervisor_user).action_supervisor_approve()
        self.thesis_ft.with_user(self.co_supervisor_user).action_supervisor_approve()
        with self.assertRaises(AccessError):
            self.env['campus.thesis.progress'].with_user(self.advisor_user).create({
                'thesis_id': self.thesis_ft.id,
                'stage': 'proposal',
                'milestone': 'Fake PA Log',
                'description': 'Should fail',
                'state': 'approved',
            })
        log = self.env['campus.thesis.progress'].sudo().create({
            'thesis_id': self.thesis_ft.id,
            'stage': 'proposal',
            'milestone': 'Bab I',
            'description': 'Student draft',
            'progress_percent': 30.0,
        })
        with self.assertRaises(AccessError):
            log.with_user(self.supervisor_user).write({'milestone': 'Supervisor Rewrote Milestone'})
        # Raw write of review state without action_approve/action_request_revision is also blocked
        with self.assertRaises(AccessError):
            log.with_user(self.supervisor_user).write({'state': 'approved'})

    def test_lecturer_cannot_edit_title_name_or_trigger_staff_actions(self):
        with self.assertRaises(AccessError):
            self.thesis_ft.with_user(self.supervisor_user).write({'title': 'Rewritten by Lecturer'})
        with self.assertRaises(AccessError):
            self.thesis_ft.with_user(self.supervisor_user).write({'name': 'SKR/FORGED'})
        with self.assertRaises(AccessError):
            self.thesis_ft.with_user(self.supervisor_user).action_submit_supervisor()

    def test_staff_cannot_forge_protected_fields_on_create_or_drop_required_yudisium_doc(self):
        base_group = self.env.ref('base.group_user')
        staff_user = self.env['res.users'].create({
            'name': '%s Staf TU Audit' % TAG,
            'login': 'zz.tu.audit.thesis@contoh.test',
            'group_ids': [Command.set([base_group.id])],
        })
        staff_emp = self.env['hr.employee'].create({
            'name': '%s Staf Audit FT' % TAG,
            'academic_role': 'academic',
            'faculty_id': self.faculty.id,
            'user_id': staff_user.id,
        })
        self.env['campus.jurisdiction'].create({
            'employee_id': staff_emp.id,
            'scope': 'academic',
            'faculty_ids': [Command.set([self.faculty.id])],
        })
        with self.assertRaises(AccessError):
            self.env['campus.thesis'].with_user(staff_user).create({
                'student_id': self.student.id,
                'academic_year_id': self.year.id,
                'title': 'Forged Approval Create',
                'supervisor_id': self.supervisor_emp.id,
                'yudisium_dean_approved': True,
            })

        self.thesis_ft._ensure_default_documents()
        req_doc = self.thesis_ft.yudisium_document_ids.filtered('required')[:1]
        with self.assertRaises(AccessError):
            req_doc.with_user(staff_user).write({'required': False})
        with self.assertRaises(AccessError):
            req_doc.with_user(staff_user).unlink()
