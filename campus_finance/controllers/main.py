import logging
from urllib.parse import urlencode

from odoo import http, _
from odoo.exceptions import ValidationError
from odoo.http import request
from odoo.addons.campus_pmb.controllers.main import CampusPMBWebsite

_logger = logging.getLogger(__name__)

class CampusFinanceWebsite(CampusPMBWebsite):

    @http.route('/admission/submit', type='http', auth="public", methods=['POST'], website=True, csrf=True)
    def admission_submit(self, **post):
        try:
            faculty_id = int(post.get('faculty_id')) if post.get('faculty_id') else False
            program_id = int(post.get('program_id')) if post.get('program_id') else False
            
            if program_id:
                program = request.env['academic.program'].sudo().browse(program_id)
                if faculty_id and program.faculty_id.id != faculty_id:
                    raise ValidationError(_("Program does not belong to the selected faculty."))
                if not faculty_id:
                    faculty_id = program.faculty_id.id

            active_year = request.env['academic.year'].sudo().search([('active', '=', True)], order='id desc', limit=1)
            if not active_year:
                raise ValidationError(_("No active academic year found for admission."))

            # Create the admission record in Draft state
            admission = request.env['campus.admission'].sudo().create({
                'name': post.get('name'),
                'email': post.get('email'),
                'phone': post.get('phone'),
                'previous_school': post.get('previous_school'),
                'faculty_id': faculty_id,
                'program_id': program_id,
                'academic_year_id': active_year.id,
                'admission_path': post.get('admission_path', 'regular'),
                'state': 'draft',  # Set it to draft, waiting for payment
            })
            
            # Create the Registration Invoice
            invoice = admission._create_registration_invoice()
            
            # Redirect to the Odoo standard payment portal for this invoice
            access_url = invoice.get_portal_url()
            return request.redirect(access_url)

        except Exception:
            _logger.exception("Admission submit failed for email: %s", post.get('email'))
            user_msg = _("Submission failed. An application with this email may already exist, or data is invalid.")
            return request.redirect('/admission?' + urlencode({'error': user_msg}))
