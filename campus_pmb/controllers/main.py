import logging
from urllib.parse import urlencode

from odoo import http, _
from odoo.exceptions import ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)


class CampusPMBWebsite(http.Controller):

    @http.route('/admission', type='http', auth="public", website=True)
    def admission_form(self, **kw):
        faculties = request.env['academic.faculty'].sudo().search([])
        programs = request.env['academic.program'].sudo().search([])
        
        values = {
            'faculties': faculties,
            'programs': programs,
            'page_name': 'admission_form',
            'error': kw.get('error'),
        }
        return request.render("campus_pmb.admission_form", values)

    @http.route('/admission/submit', type='http', auth="public", methods=['POST'], website=True, csrf=True)
    def admission_submit(self, **post):
        try:
            request.env['campus.admission'].sudo().create_admission_from_portal(post)
            return request.redirect('/admission/thanks')
        except Exception:
            _logger.exception("Admission submit failed for email: %s", post.get('email'))
            user_msg = _("Submission failed. An application with this email may already exist, or data is invalid.")
            return request.redirect('/admission?' + urlencode({'error': user_msg}))

    @http.route('/admission/thanks', type='http', auth="public", website=True)
    def admission_thanks(self, **kw):
        return request.render("campus_pmb.admission_thanks", {})
