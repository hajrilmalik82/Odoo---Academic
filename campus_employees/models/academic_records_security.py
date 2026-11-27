from odoo import _, models
from odoo.exceptions import AccessError


def _check_program_in_academic_jurisdiction(env, program):
    """Ensure Academic Staff cannot move records to a program outside their jurisdiction.

    Enforced before ORM business constraints so out-of-scope transfers always
    fail with AccessError rather than leaking foreign program/faculty metadata
    through ValidationError.
    """
    user = env.user
    if env.su or user.has_group('campus_core.group_campus_administrator'):
        return
    if not user.has_group('campus_core.group_campus_academic_staff'):
        return
    rows = user.employee_ids.sudo().jurisdiction_ids.filtered(lambda j: j.scope == 'academic')
    if not any(row._covers_program(program) for row in rows):
        raise AccessError(_(
            "You are not authorized to transfer academic records outside your assigned jurisdiction."
        ))


class AcademicKrs(models.Model):
    _inherit = 'academic.krs'

    def write(self, vals):
        if not self.env.su:
            if 'program_id' in vals:
                target_prog = (
                    self.env['academic.program'].sudo().browse(vals['program_id'])
                    if vals['program_id'] else self.env['academic.program']
                )
                _check_program_in_academic_jurisdiction(self.env, target_prog)
            if 'student_id' in vals:
                target_student = (
                    self.env['res.partner'].sudo().browse(vals['student_id'])
                    if vals['student_id'] else self.env['res.partner']
                )
                _check_program_in_academic_jurisdiction(self.env, target_student.program_id)
        res = super().write(vals)
        if not self.env.su and ('student_id' in vals or 'program_id' in vals):
            self.flush_recordset()
            self.check_access('write')
        return res


class AcademicKrsLine(models.Model):
    _inherit = 'academic.krs.line'

    def write(self, vals):
        res = super().write(vals)
        if not self.env.su and 'krs_id' in vals:
            self.flush_recordset()
            self.check_access('write')
        return res


class AcademicKhs(models.Model):
    _inherit = 'academic.khs'

    def write(self, vals):
        res = super().write(vals)
        if not self.env.su and 'student_id' in vals:
            self.flush_recordset()
            self.check_access('write')
        return res


class AcademicKhsLine(models.Model):
    _inherit = 'academic.khs.line'

    def write(self, vals):
        res = super().write(vals)
        if not self.env.su and 'khs_id' in vals:
            self.flush_recordset()
            self.check_access('write')
        return res
