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
            admission = request.env['campus.admission'].create_admission_from_portal(post)
            
            # Create the Registration Invoice
            invoice = admission._create_registration_invoice()
            
            # Redirect to the Odoo standard payment portal for this invoice
            access_url = invoice.get_portal_url()
            return request.redirect(access_url)

        except Exception:
            _logger.exception("Admission submit failed for email: %s", post.get('email'))
            user_msg = _("Submission failed. An application with this email may already exist, or data is invalid.")
            return request.redirect('/admission?' + urlencode({'error': user_msg}))
