import json
import logging

from odoo import http, _
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)

class CampusPMBWebsite(http.Controller):
    """Public JSON REST API for the standalone React frontend-app."""

    @staticmethod
    def _track_descriptions():
        return {
            'regular': _("Regular admission track based on academic aptitude assessment."),
            'scholarship': _("Merit scholarship track with configured fee exemptions."),
            'transfer': _("Transfer admission track with prior credit recognition."),
        }

    @http.route(
        '/api/admission/options',
        type='http', auth='public', methods=['GET', 'OPTIONS'],
        csrf=False, cors='*', readonly=True,
    )
    def api_admission_options(self, **kw):
        if request.httprequest.method == 'OPTIONS':
            return request.make_response('', headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With',
            })
        faculties = request.env['academic.faculty'].sudo().search([])
        programs = request.env['academic.program'].sudo().search([])
        Fee = request.env['campus.admission.fee'].sudo()
        all_fee_rules = Fee.search([])
        path_selection = request.env['campus.admission']._admission_path_selection()
        paths = [key for key, _label in path_selection]

        fee_matrix = {}
        for path in paths:
            fee_matrix[path] = {}
            for prog in [None] + list(programs):
                prog_key = str(prog.id) if prog else ''
                reg_amount = Fee._get_fee_amount(
                    'registration', admission_path=path, program=prog, rules=all_fee_rules,
                )
                rereg_amount = Fee._get_fee_amount(
                    'reregistration', admission_path=path, program=prog, rules=all_fee_rules,
                )
                fee_matrix[path][prog_key] = {
                    'registration': reg_amount,
                    'reregistration': rereg_amount,
                }

        faculty_list = [
            {
                'id': str(fac.id),
                'name': fac.name,
                'code': fac.code or '',
                'description': _("Higher education programs offered by %s.") % fac.name,
            }
            for fac in faculties
        ]

        program_list = [
            {
                'id': str(prog.id),
                'name': prog.name,
                'code': prog.code or '',
                'degree': 'S1',
                'facultyId': str(prog.faculty_id.id),
                'tuitionFee': fee_matrix.get('regular', {}).get(str(prog.id), {}).get(
                    'reregistration', 0.0,
                ),
            }
            for prog in programs
        ]

        descriptions = self._track_descriptions()
        base_rereg = fee_matrix.get('regular', {}).get('', {}).get('reregistration', 0.0)
        track_list = []
        for key, label in path_selection:
            track_rereg = fee_matrix.get(key, {}).get('', {}).get('reregistration', 0.0)
            discount_pct = 0
            if base_rereg > 0 and track_rereg < base_rereg:
                discount_pct = max(0, min(100, round(100 * (base_rereg - track_rereg) / base_rereg)))
            track_list.append({
                'id': key,
                'name': label,
                'description': descriptions.get(key, label),
                'registrationFee': fee_matrix.get(key, {}).get('', {}).get('registration', 0.0),
                'discountPercentage': discount_pct,
            })

        default_rereg_fee = base_rereg
        return request.make_json_response({
            'status': 'success',
            'data': {
                'faculties': faculty_list,
                'studyPrograms': program_list,
                'admissionTracks': track_list,
                'feeMatrix': fee_matrix,
                'defaultReRegistrationFee': default_rereg_fee,
            },
        })

    def _extract_payload(self):
        raw = request.httprequest.get_data(as_text=True)
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except ValueError:
                pass
        return dict(request.params)

    @http.route(
        '/api/admission/submit',
        type='http', auth='public', methods=['POST', 'OPTIONS'],
        csrf=False, cors='*',
    )
    def api_admission_submit(self, **post):
        if request.httprequest.method == 'OPTIONS':
            return request.make_response('', headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With',
            })
        try:
            payload = self._extract_payload()
            normalized = {
                'name': (payload.get('fullName') or payload.get('name') or '').strip(),
                'email': (payload.get('email') or '').strip(),
                'phone': (payload.get('phoneNumber') or payload.get('phone') or '').strip(),
                'previous_school': (
                    payload.get('schoolOrigin') or payload.get('previous_school') or ''
                ).strip(),
                'faculty_id': payload.get('facultyId') or payload.get('faculty_id'),
                'program_id': payload.get('studyProgramId') or payload.get('program_id'),
                'admission_path': (
                    payload.get('admissionTrackId') or payload.get('admission_path') or 'regular'
                ),
            }
            admission = (
                request.env['campus.admission']
                .sudo()
                ._create_admission_from_portal(normalized)
            )
            return request.make_json_response(
                {
                    'status': 'success',
                    'data': {
                        'id': admission.id,
                        'registrationNumber': admission.registration_number,
                        'fullName': admission.name,
                        'email': admission.email,
                        'phoneNumber': admission.phone or '',
                        'schoolOrigin': admission.previous_school or '',
                        'facultyId': str(admission.faculty_id.id),
                        'facultyName': admission.faculty_id.name,
                        'studyProgramId': str(admission.program_id.id),
                        'studyProgramName': admission.program_id.name,
                        'admissionTrackId': admission.admission_path,
                        'registrationFee': admission.registration_fee,
                        'reRegistrationFee': admission.reregistration_fee,
                        'state': admission.state,
                    },
                },
                status=201,
            )
        except (ValidationError, UserError) as error:
            user_msg = error.args[0] if error.args else _("Submission failed.")
            return request.make_json_response(
                {'status': 'error', 'message': user_msg},
                status=400,
            )
        except Exception:
            _logger.exception("Admission API submit failed")
            user_msg = _(
                "Submission failed because of a system error. Please try again later."
            )
            return request.make_json_response(
                {'status': 'error', 'message': user_msg},
                status=500,
            )
