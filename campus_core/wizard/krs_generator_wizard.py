from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class KrsGeneratorWizard(models.TransientModel):
    _name = 'krs.generator.wizard'
    _description = 'KRS Generator Wizard'

    package_id = fields.Many2one('academic.course.package', string='Course Package', required=True, readonly=True)
    academic_year_id = fields.Many2one(related='package_id.academic_year_id', string='Academic Year')
    program_id = fields.Many2one(related='package_id.program_id', string='Study Program')
    
    student_ids = fields.Many2many('res.partner', string='Students', domain="[('is_student', '=', True), ('program_id', '=', program_id)]")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('active_model') == 'academic.course.package' and self.env.context.get('active_id'):
            package_id = self.env.context.get('active_id')
            package = self.env['academic.course.package'].browse(package_id)
            res['package_id'] = package.id
            
            # Default students: all students in the program who don't have a KRS for this year
            students = self.env['res.partner'].search([
                ('is_student', '=', True),
                ('program_id', '=', package.program_id.id)
            ])
            existing_krs = self.env['academic.krs'].search([
                ('academic_year_id', '=', package.academic_year_id.id),
                ('student_id', 'in', students.ids)
            ])
            students_with_krs = existing_krs.mapped('student_id').ids
            valid_students = students.filtered(lambda s: s.id not in students_with_krs)
            
            res['student_ids'] = [(6, 0, valid_students.ids)]
            
        return res

    def action_generate_krs(self):
        self.ensure_one()
        if not self.student_ids:
            raise ValidationError(_("Please select at least one student."))
            
        krs_obj = self.env['academic.krs']
        created_count = 0
        
        for student in self.student_ids:
            # Check again to avoid concurrent duplicates
            existing = krs_obj.search([
                ('academic_year_id', '=', self.package_id.academic_year_id.id),
                ('student_id', '=', student.id)
            ], limit=1)
            
            if existing:
                continue
                
            # Prepare new KRS
            new_krs = krs_obj.create({
                'student_id': student.id,
                'package_id': self.package_id.id,
                'academic_year_id': self.package_id.academic_year_id.id,
                'program_id': self.package_id.program_id.id,
                'faculty_id': self.package_id.program_id.faculty_id.id,
            })
            
            # Apply lines safely via write()
            new_krs._apply_package_lines(self.package_id)
            
            created_count += 1
            
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('%s KRS draft(s) successfully generated!' % created_count),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
