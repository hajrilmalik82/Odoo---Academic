from odoo import fields, models


class AcademicClassSchedule(models.Model):
    """Restrict the Lecturer picker to academic lecturers of the right faculty.

    The domain lives here rather than on the field in campus_core because it
    reads academic_role, program_id and faculty_id, which this module adds to
    hr.employee. campus_core cannot see them: campus_employees depends on
    campus_core, so the reverse dependency would be a cycle, and stating the
    domain there made campus_core fail to install on its own with
    "Unknown field hr.employee.program_id in domain of python field lecturer_id".

    The domain also reads class_program_id and class_faculty_id from the record
    being edited. Those are campus_core fields, but a dynamic domain is
    evaluated by the client against the form, so both are carried as invisible
    fields in the two views where a lecturer is actually picked.
    """

    _inherit = 'academic.class.schedule'

    lecturer_id = fields.Many2one(
        'hr.employee',
        domain="[('academic_role', '=', 'lecturer'), '|',"
               " ('program_id', '=', class_program_id),"
               " ('faculty_id', '=', class_faculty_id)]",
    )
