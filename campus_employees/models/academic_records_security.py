from odoo import models


class AcademicKrs(models.Model):
    _inherit = 'academic.krs'

    def write(self, vals):
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
