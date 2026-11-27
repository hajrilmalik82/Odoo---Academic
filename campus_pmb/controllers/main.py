import json
import logging

from psycopg2 import IntegrityError

from odoo import http, _
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)

_MAX_API_BODY_BYTES = 16 * 1024  # 16 KB cap against unauthenticated RAM DoS


class CampusPMBWebsite(http.Controller):
    """Public JSON REST API for the standalone admission frontend."""

    @staticmethod
    def _cors_origin():
        return (
            request.env['ir.config_parameter']
            .sudo()
            .get_param('campus_pmb.cors_origin', '*')
            or '*'
        )

    @staticmethod
    def _track_descriptions():
        return {
            'regular': _("Regular admission track based on academic aptitude assessment."),
            'scholarship': _("Merit scholarship track with configured fee exemptions."),
            'transfer': _("Transfer admission track with prior credit recognition."),
        }

    @staticmethod
    def _first_present(payload, *keys, default=''):
        for key in keys:
            if key in payload and payload[key] is not None:
                return payload[key]
        return default

    @http.route(
        '/api/admission/options',
        type='http', auth='public', methods=['GET', 'OPTIONS'],
        csrf=False, cors='*', readonly=True,
    )
    def api_admission_options(self, **kw):
        origin = self._cors_origin()
        if request.httprequest.method == 'OPTIONS':
            return request.make_response('', headers={
                'Access-Control-Allow-Origin': origin,
                'Access-Control-Allow-Methods': 'GET, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With',
            })
        faculties = request.env['academic.faculty'].sudo().search([])
        programs = request.env['academic.program'].sudo().search([])
        Fee = request.env['campus.admission.fee'].sudo()
        fee_index = Fee._build_fee_index()
        path_selection = request.env['campus.admission']._admission_path_selection()
        paths = [key for key, _label in path_selection]

        fee_matrix = {}
        for path in paths:
            fee_matrix[path] = {}
            for prog in [None] + list(programs):
                prog_key = str(prog.id) if prog else ''
                reg_amount = Fee._lookup_fee_from_index(fee_index, 'registration', path, prog)
                rereg_amount = Fee._lookup_fee_from_index(fee_index, 'reregistration', path, prog)
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

        return request.make_json_response(
            {
                'status': 'success',
                'data': {
                    'faculties': faculty_list,
                    'studyPrograms': program_list,
                    'admissionTracks': track_list,
                    'feeMatrix': fee_matrix,
                    'defaultReRegistrationFee': base_rereg,
                },
            },
            headers={'Cache-Control': 'public, max-age=60'},
        )

    def _extract_payload(self):
        content_length = request.httprequest.content_length
        if content_length and content_length > _MAX_API_BODY_BYTES:
            raise ValidationError(_("Request payload is too large."))
        raw_bytes = request.httprequest.get_data(cache=False)
        if len(raw_bytes) > _MAX_API_BODY_BYTES:
            raise ValidationError(_("Request payload is too large."))
        raw = raw_bytes.decode('utf-8', errors='strict') if raw_bytes else ''
        content_type = (request.httprequest.content_type or '').lower()
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
                if 'application/json' in content_type:
                    raise ValidationError(_("Invalid JSON request payload."))
            except ValueError:
                if 'application/json' in content_type:
                    raise ValidationError(_("Invalid JSON request payload."))
        return dict(request.params)

    @http.route(
        '/api/admission/submit',
        type='http', auth='public', methods=['POST', 'OPTIONS'],
        csrf=False, cors='*',
    )
    def api_admission_submit(self, **post):
        origin = self._cors_origin()
        if request.httprequest.method == 'OPTIONS':
            return request.make_response('', headers={
                'Access-Control-Allow-Origin': origin,
                'Access-Control-Allow-Methods': 'POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With',
            })
        try:
            payload = self._extract_payload()
            normalized = {
                'name': self._first_present(payload, 'fullName', 'name', default=''),
                'email': self._first_present(payload, 'email', default=''),
                'phone': self._first_present(payload, 'phoneNumber', 'phone', default=''),
                'previous_school': self._first_present(payload, 'schoolOrigin', 'previous_school', default=''),
                'faculty_id': self._first_present(payload, 'facultyId', 'faculty_id', default=None),
                'program_id': self._first_present(payload, 'studyProgramId', 'program_id', default=None),
                'admission_path': self._first_present(
                    payload, 'admissionTrackId', 'admission_path', default='regular',
                ),
            }
            with request.env.cr.savepoint():
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
        except (ValidationError, UserError, UnicodeDecodeError) as error:
            user_msg = (
                _("Invalid UTF-8 request encoding.")
                if isinstance(error, UnicodeDecodeError)
                else (error.args[0] if error.args else _("Submission failed."))
            )
            return request.make_json_response(
                {'status': 'error', 'message': user_msg},
                status=400,
            )
        except IntegrityError as err:
            if getattr(err, 'pgcode', None) == '23505':
                user_msg = _(
                    "An application with this email address already exists for this "
                    "academic year. Please contact the admissions office if you need "
                    "to change it."
                )
                return request.make_json_response(
                    {'status': 'error', 'message': user_msg},
                    status=400,
                )
            _logger.exception("Admission API submit hit unexpected IntegrityError")
            return request.make_json_response(
                {
                    'status': 'error',
                    'message': _("Submission failed because of a system error. Please try again later."),
                },
                status=500,
            )
        except Exception:
            _logger.exception("Admission API submit failed")
            return request.make_json_response(
                {
                    'status': 'error',
                    'message': _("Submission failed because of a system error. Please try again later."),
                },
                status=500,
            )
