from odoo import fields, models

# Who may be put in front of a class.
#
# A lecturer of the programme the subject belongs to, OR of its faculty. The OR
# is deliberate and is the difference from the rule on dean_id and head_id in
# academic_institution.py: teaching a subject outside your own programme but
# inside your faculty is ordinary, heading somebody else's programme is not.
#
# Written once and shared, because academic.class.schedule and
# academic.class.session hold the same field for the same reason - a session is
# an instance of a schedule, and its lecturer is copied from one. Spelled out
# twice, the two would drift.
#
# class_program_id and class_faculty_id are campus_core fields, related through
# class_id.subject_id. A dynamic domain is evaluated by the CLIENT against the
# form, so both have to be present in every view where a lecturer is picked -
# invisible is enough, absent is not. Leaving them out does not raise anything:
# the domain silently stops narrowing and the picker offers every employee.
LECTURER_DOMAIN = (
    "[('academic_role', '=', 'lecturer'), '|',"
    " ('program_id', '=', class_program_id),"
    " ('faculty_id', '=', class_faculty_id)]"
)


class AcademicClassSchedule(models.Model):
    """Restrict the Lecturer picker on the weekly schedule.

    The domain lives here rather than on the field in campus_core because it
    reads academic_role, program_id and faculty_id, which this module adds to
    hr.employee. campus_core cannot see them: campus_employees depends on
    campus_core, so the reverse dependency would be a cycle, and stating the
    domain there made campus_core fail to install on its own with
    "Unknown field hr.employee.program_id in domain of python field lecturer_id".
    """

    _inherit = 'academic.class.schedule'

    lecturer_id = fields.Many2one('hr.employee', domain=LECTURER_DOMAIN)


class AcademicClassSession(models.Model):
    """Restrict the Lecturer picker on a single session.

    Sessions are generated from the weekly schedule and copy its lecturer, so
    the data starts out right. The field is editable on the session form all the
    same - a stand-in for one week is a real need - and until this existed that
    one form was the only place in the suite where the lecturer list was every
    employee in the company, Odoo's own demo staff included.
    """

    _inherit = 'academic.class.session'

    lecturer_id = fields.Many2one('hr.employee', domain=LECTURER_DOMAIN)
