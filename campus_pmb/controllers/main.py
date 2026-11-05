import json
import logging
from urllib.parse import urlencode

from odoo import http, _
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
from odoo.tools.misc import format_amount

_logger = logging.getLogger(__name__)


class CampusPMBWebsite(http.Controller):

    @http.route('/admission', type='http', auth="public", website=True, sitemap=True)
    def admission_form(self, **kw):
        # Scoped to this website's company plus the company-less rows. sudo()
        # bypasses record rules, so without a clause here a multi-company
        # database offered an anonymous visitor every institution's faculties
        # and programmes in one dropdown. _create_admission_from_portal applies
        # the same domain, so a hand-crafted POST cannot pick another one.
        company = request.env.company
        company_domain = ['|', ('company_id', '=', False),
                          ('company_id', '=', company.id)]
        faculties = request.env['academic.faculty'].sudo().search(company_domain)
        programs = request.env['academic.program'].sudo().search(company_domain)

        Fee = request.env['campus.admission.fee'].sudo()
        paths = [key for key, _label in request.env['campus.admission']._admission_path_selection()]
        currency = company.currency_id
        fee_matrix = {}
        for path in paths:
            fee_matrix[path] = {}
            for prog in [None] + list(programs):
                prog_key = str(prog.id) if prog else ''
                reg_amount = Fee._get_fee_amount('registration', admission_path=path, program=prog, company=company)
                rereg_amount = Fee._get_fee_amount('reregistration', admission_path=path, program=prog, company=company)
                fee_matrix[path][prog_key] = {
                    'registration': format_amount(request.env, reg_amount, currency),
                    'reregistration': format_amount(request.env, rereg_amount, currency),
                }

        default_fees = fee_matrix.get('regular', {}).get('', {'registration': '-', 'reregistration': '-'})
        values = {
            'faculties': faculties,
            'programs': programs,
            'fee_matrix_json': json.dumps(fee_matrix),
            'default_registration_fee': default_fees['registration'],
            'default_reregistration_fee': default_fees['reregistration'],
            'page_name': 'admission_form',
            'error': kw.get('error'),
        }
        return request.render("campus_pmb.admission_form", values)

    @http.route('/admission/submit', type='http', auth="public", methods=['POST'], website=True, csrf=True)
    def admission_submit(self, **post):
        try:
            request.env['campus.admission'].sudo()._create_admission_from_portal(post)
            return request.redirect('/admission/thanks')
        except (ValidationError, UserError) as error:
            # A rule the applicant can act on: a duplicate email, a programme
            # that does not belong to the chosen faculty, a bad selection. Show
            # what actually went wrong instead of one message for everything.
            user_msg = error.args[0] if error.args else _("Submission failed.")
            return request.redirect('/admission?' + urlencode({'error': user_msg}))
        except Exception:
            # Anything else is our bug, not theirs. Logged with a traceback, and
            # reported without leaking internals to an anonymous visitor.
            _logger.exception("Admission submit failed for email: %s", post.get('email'))
            user_msg = _("Submission failed because of a system error. Please try again later.")
            return request.redirect('/admission?' + urlencode({'error': user_msg}))

    # sitemap=False: a thank-you page has nothing to index and Odoo logs a
    # warning for every public route that leaves the value unstated.
    @http.route('/admission/thanks', type='http', auth="public", website=True, sitemap=False)
    def admission_thanks(self, **kw):
        return request.render("campus_pmb.admission_thanks", {})
