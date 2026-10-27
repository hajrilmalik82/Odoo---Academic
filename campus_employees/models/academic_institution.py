from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AcademicFaculty(models.Model):
    """Who may be made dean of a faculty.

    campus_core declares dean_id without a domain, and has to: academic_role and
    faculty_id on hr.employee belong to THIS module, and campus_core must not
    know about them - it carries no dependency on campus_employees, the
    dependency runs the other way. Narrowing the field here is the only layering
    that works, and it narrows it everywhere the field is used rather than in one
    form view.
    """
    _inherit = 'academic.faculty'

    # The ('faculty_id', '!=', False) clause looks redundant beside the equality
    # under it, and is not. On a faculty that has not been saved yet `id`
    # evaluates to False, and the equality alone then reads as
    # ('faculty_id', '=', False) - which offers every lecturer who has no faculty
    # at all. With both clauses the pair cannot be satisfied and the list comes
    # back empty, which is the truth: a faculty that does not exist yet has
    # nobody to promote.
    dean_id = fields.Many2one(
        domain="[('academic_role', '=', 'lecturer'),"
               " ('faculty_id', '!=', False),"
               " ('faculty_id', '=', id)]",
    )

    @api.constrains('dean_id')
    def _check_dean_is_a_lecturer_of_the_faculty(self):
        """A domain only steers a dropdown. An import, a server action or a
        paste into the list view writes the field without ever consulting it."""
        for faculty in self.filtered('dean_id'):
            dean = faculty.dean_id
            if dean.academic_role != 'lecturer':
                raise ValidationError(_(
                    "%(person)s is not a lecturer, so they cannot be dean of %(faculty)s.",
                    person=dean.name,
                    faculty=faculty.name,
                ))
            if dean.faculty_id != faculty:
                raise ValidationError(_(
                    "%(person)s belongs to %(their_faculty)s, so they cannot be dean of"
                    " %(faculty)s. Move them first, or pick a lecturer of this faculty.",
                    person=dean.name,
                    their_faculty=dean.faculty_id.name or _("no faculty"),
                    faculty=faculty.name,
                ))


class AcademicProgram(models.Model):
    """Who may head a study programme. Same rule as the dean, one level down:
    the head is a lecturer OF that programme, not merely of its faculty."""
    _inherit = 'academic.program'

    head_id = fields.Many2one(
        domain="[('academic_role', '=', 'lecturer'),"
               " ('program_id', '!=', False),"
               " ('program_id', '=', id)]",
    )

    @api.constrains('head_id')
    def _check_head_is_a_lecturer_of_the_program(self):
        for program in self.filtered('head_id'):
            head = program.head_id
            if head.academic_role != 'lecturer':
                raise ValidationError(_(
                    "%(person)s is not a lecturer, so they cannot head %(program)s.",
                    person=head.name,
                    program=program.name,
                ))
            if head.program_id != program:
                raise ValidationError(_(
                    "%(person)s teaches on %(their_program)s, so they cannot head"
                    " %(program)s. Move them first, or pick a lecturer of this programme.",
                    person=head.name,
                    their_program=head.program_id.name or _("no programme"),
                    program=program.name,
                ))
