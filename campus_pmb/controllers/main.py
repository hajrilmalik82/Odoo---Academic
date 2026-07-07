import logging

from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class CampusPMBWebsite(http.Controller):

    @http.route('/admission', type='http', auth="public", website=True)
    def admission_form(self, **kw):
        programs = request.env['academic.program'].sudo().search([])
        academic_years = request.env['academic.year'].sudo().search([])
        
        values = {
            'programs': programs,
            'academic_years': academic_years,
            'page_name': 'admission_form',
            'error': kw.get('error'),
        }
        return request.render("campus_pmb.admission_form", values)

    @http.route('/admission/submit', type='http', auth="public", methods=['POST'], website=True, csrf=True)
    def admission_submit(self, **post):
        try:
            # Sudo is required because public users don't have write access to campus.admission
            request.env['campus.admission'].sudo().create({
                'name': post.get('name'),
                'email': post.get('email'),
                'phone': post.get('phone'),
                'previous_school': post.get('previous_school'),
                'program_id': int(post.get('program_id')) if post.get('program_id') else False,
                'academic_year_id': int(post.get('academic_year_id')) if post.get('academic_year_id') else False,
                'admission_path': post.get('admission_path', 'regular'),
            })
            return request.redirect('/admission/thanks')
        except Exception as e:
            _logger.exception("Admission submit failed for email: %s", post.get('email'))
            user_msg = _("Submission failed. An application with this email may already exist, or data is invalid.")
            return request.redirect('/admission?error=' + str(user_msg))

    @http.route('/admission/thanks', type='http', auth="public", website=True)
    def admission_thanks(self, **kw):
        return request.render("campus_pmb.admission_thanks", {})
