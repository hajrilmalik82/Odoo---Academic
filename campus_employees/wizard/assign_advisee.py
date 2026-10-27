from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CampusAdviseeAssign(models.TransientModel):
    """Point existing students at an academic advisor.

    The Advisees button used to open the contact list with Odoo's New button on
    it, which invited somebody to create a student from here. A student is not
    created by hand: they arrive through the admissions flow in campus_pmb,
    which is what issues the NIM and links the programme. Creation is switched
    off on that list, and this is what replaces it - choosing among the students
    who already exist.
    """

    _name = 'campus.advisee.assign'
    _description = 'Assign Students to an Academic Advisor'

    advisor_id = fields.Many2one(
        'hr.employee', string="Academic Advisor", required=True, readonly=True)
    advisor_program_id = fields.Many2one(related='advisor_id.program_id', string="Advisor's Programme")
    advisor_faculty_id = fields.Many2one(related='advisor_id.faculty_id', string="Advisor's Faculty")
    student_ids = fields.Many2many(
        'res.partner',
        string="Students",
        # Narrowed to the advisor's own programme, the same rule res_partner.py
        # puts on academic_advisor_id and enforces with a constraint. Offering a
        # student the wizard cannot legally assign would be a list of traps.
        #
        # ('program_id', '!=', False) guards the case where the advisor has no
        # programme: the equality alone would then read as
        # ('program_id', '=', False) and offer every student not yet enrolled
        # anywhere.
        #
        # '!=' rather than '= False' on the advisor: Odoo reads an inequality on
        # a many2one as "different, or not set", so students with no advisor at
        # all are offered too, while the ones this advisor already has are not.
        domain="[('is_student', '=', True),"
               " ('student_status', '=', 'active'),"
               " ('program_id', '!=', False),"
               " ('program_id', '=', advisor_program_id),"
               " ('academic_advisor_id', '!=', advisor_id)]",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('active_model') == 'hr.employee' and self.env.context.get('active_id'):
            res.setdefault('advisor_id', self.env.context['active_id'])
        return res

    def action_assign(self):
        self.ensure_one()
        if not self.student_ids:
            raise ValidationError(_("Pick at least one student to assign."))
        # One write for the whole selection: assigning a cohort of forty used to
        # be the obvious place for a loop, and a loop here is forty round trips.
        self.student_ids.write({'academic_advisor_id': self.advisor_id.id})
        return {'type': 'ir.actions.act_window_close'}
