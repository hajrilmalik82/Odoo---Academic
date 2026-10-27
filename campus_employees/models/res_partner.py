from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    """An academic advisor belongs to the student's own programme.

    campus_core declares academic_advisor_id without a domain, and has to:
    academic_role and program_id on hr.employee belong to THIS module, and the
    dependency runs campus_employees -> campus_core, never the other way.

    The narrowing used to live in two <field position="attributes"> overrides in
    views/res_partner_views.xml. Two is already one too many - a third view
    showing the field would quietly have offered every lecturer in the campus -
    and neither of them stopped an import, a server action or a list-view paste.
    On the field it holds everywhere, and the constraint below holds even where
    no form is involved.
    """

    _inherit = 'res.partner'

    # Both sides are spelled program_id and they are different things: the
    # first is hr.employee.program_id, the field being searched; the last is
    # this student's own, read off the record the domain is evaluated against.
    #
    # ('program_id', '!=', False) is not redundant beside the equality. A
    # student whose programme is not set yet makes the equality read as
    # ('program_id', '=', False), which offers every lecturer who has no
    # programme either. With both clauses the pair cannot be satisfied and the
    # list is empty - the truth, since there is no programme to belong to yet.
    academic_advisor_id = fields.Many2one(
        domain="[('academic_role', '=', 'lecturer'),"
               " ('program_id', '!=', False),"
               " ('program_id', '=', program_id)]",
    )

    @api.constrains('academic_advisor_id', 'program_id')
    def _check_advisor_shares_the_programme(self):
        """Watches the student's programme as well as the advisor.

        Moving a student to another programme is the quiet half of this rule:
        the advisor field is not touched, so a constraint on it alone would
        never fire, and the student would be left with an advisor from the
        programme they just left.

        The other direction - moving the LECTURER - is refused outright while
        they still advise anybody, by the guard in hr_employee.py.
        """
        for student in self.filtered('academic_advisor_id'):
            advisor = student.academic_advisor_id
            if advisor.academic_role != 'lecturer':
                raise ValidationError(_(
                    "%(person)s is not a lecturer, so they cannot be the academic"
                    " advisor of %(student)s.",
                    person=advisor.name,
                    student=student.name,
                ))
            if advisor.program_id != student.program_id:
                raise ValidationError(_(
                    "%(person)s teaches on %(advisor_program)s while %(student)s is"
                    " enrolled on %(student_program)s. An academic advisor belongs to"
                    " the student's own programme: pick a different advisor, or move"
                    " the student first.",
                    person=advisor.name,
                    advisor_program=advisor.program_id.name or _("no programme"),
                    student=student.name,
                    student_program=student.program_id.name or _("no programme"),
                ))
