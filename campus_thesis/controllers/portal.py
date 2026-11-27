import base64
import io
import logging
import math
import ntpath
import os
import re
import zipfile

from odoo import http, _
from odoo.addons.campus_core.portal_utils import (
    pop_flash_messages,
    redirect_with_error as _redirect_with_error,
    redirect_with_success as _redirect_with_success,
    report_errors_to as _shared_report_errors_to,
)
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
from odoo.tools import str2bool

_logger = logging.getLogger(__name__)

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB safety cap
_MAX_FILENAME_LEN = 180
_MAX_PROGRESS_LOGS = 100
_ALLOWED_REPORT_TYPES = frozenset({'pdf', 'html'})
_ALLOWED_UPLOAD_EXTENSIONS = {'.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png'}
_DANGEROUS_UPLOAD_PREFIXES = (
    b'<!doctype html',
    b'<html',
    b'<script',
    b'<svg',
    b'<?php',
)


def report_errors_to(url_for):
    return _shared_report_errors_to(
        url_for,
        logger=_logger,
        integrity_message=_("This thesis action could not be saved because of a conflicting record."),
    )


def _thesis_page(thesis_id, *_args, **_kwargs):
    return '/my/thesis/%s' % thesis_id


class CampusThesisPortal(CustomerPortal):

    def _ensure_active_student(self, partner):
        if not partner.is_student or partner.student_status != 'active':
            raise UserError(_("Only active students can modify thesis records."))

    def _normalize_report_params(self, report_type, download):
        if report_type not in _ALLOWED_REPORT_TYPES:
            report_type = 'pdf'
        if not isinstance(download, bool):
            download = str2bool(str(download), default=False)
        return report_type, download

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id
        if 'thesis_count' in counters:
            values['thesis_count'] = request.env['campus.thesis'].sudo().search_count([
                ('student_id', '=', partner.id),
            ])
        return values

    def _get_own_thesis(self, thesis_id):
        """Return the thesis if owned by the logged-in student, else empty."""
        Thesis = request.env['campus.thesis']
        partner = request.env.user.partner_id
        thesis = Thesis.sudo().browse(thesis_id).exists()
        if not thesis or thesis.student_id != partner:
            return Thesis.sudo().browse()
        return thesis

    def _get_available_lecturers(self, program):
        Lecturer = request.env['hr.employee'].sudo()
        primary_domain = [('academic_role', '=', 'lecturer'), ('active', '=', True)]
        if program:
            primary_domain.append(('program_id', '=', program.id))
        else:
            primary_domain.append((0, '=', 1))
        primary_lecturers = Lecturer.search(primary_domain, order='name')
        co_lecturers = Lecturer.search(
            [('academic_role', '=', 'lecturer'), ('active', '=', True)], order='name',
        )
        return primary_lecturers, co_lecturers

    def _parse_supervisor_ids(self, post):
        """Parse primary and optional co-supervisor IDs from a portal form."""
        try:
            supervisor_id = int(post.get('supervisor_id') or 0)
            co_supervisor_id = int(post.get('co_supervisor_id') or 0) or False
        except (TypeError, ValueError):
            raise ValidationError(_("Please select a valid thesis supervisor."))
        if not supervisor_id:
            raise ValidationError(_("Primary thesis supervisor is required."))
        return supervisor_id, co_supervisor_id

    def _validate_upload_signature(self, raw, ext):
        head = raw[:512].lstrip().lower()
        if head.startswith(_DANGEROUS_UPLOAD_PREFIXES) or raw.startswith(b'MZ'):
            raise ValidationError(_("Executable or active script content is not allowed."))
        if ext == '.pdf':
            # Require PDF magic header at the start (after optional BOM/whitespace)
            # to reject HTML/JS polyglot payloads containing %PDF- later in bytes.
            signature_ok = raw[:64].lstrip(b'\xef\xbb\xbf \t\r\n').startswith(b'%PDF-')
        elif ext == '.png':
            signature_ok = raw.startswith(b'\x89PNG\r\n\x1a\n')
        elif ext in ('.jpg', '.jpeg'):
            signature_ok = raw.startswith(b'\xff\xd8\xff')
        elif ext == '.docx':
            signature_ok = False
            if raw.startswith(b'PK\x03\x04'):
                try:
                    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                        names = set(archive.namelist())
                    signature_ok = '[Content_Types].xml' in names and 'word/document.xml' in names
                except zipfile.BadZipFile:
                    signature_ok = False
        elif ext == '.doc':
            signature_ok = raw.startswith(b'\xd0\xcf\x11\xe0')
        else:
            signature_ok = False
        if not signature_ok:
            raise ValidationError(_(
                "Uploaded file content does not match its '%s' extension."
            ) % ext)

    def _parse_uploaded_file(self, field_name='attachment'):
        upload = request.httprequest.files.get(field_name)
        if not upload or not upload.filename:
            return None, None
        filename = os.path.basename(ntpath.basename(upload.filename)).strip()
        filename = re.sub(r'[\x00-\x1f\x7f]', '', filename)
        stem, ext = os.path.splitext(filename)
        ext = ext.lower()
        if not stem or ext not in _ALLOWED_UPLOAD_EXTENSIONS:
            raise ValidationError(_(
                "Unsupported file format '%(ext)s'. Allowed formats: PDF, DOC, DOCX, JPG, PNG."
            ) % {'ext': ext or filename or '-'})
        if len(filename) > _MAX_FILENAME_LEN:
            filename = stem[: _MAX_FILENAME_LEN - len(ext)] + ext
        raw = upload.read(_MAX_UPLOAD_BYTES + 1)
        if len(raw) > _MAX_UPLOAD_BYTES:
            raise UserError(_("Uploaded file must not exceed 10 MB."))
        if not raw:
            raise UserError(_("Uploaded file is empty."))
        self._validate_upload_signature(raw, ext)
        return base64.b64encode(raw), filename

    @http.route(['/my/thesis'], type='http', auth='user', website=True, readonly=True)
    def portal_my_thesis(self, **kw):
        partner = request.env.user.partner_id
        flash = pop_flash_messages()
        theses = request.env['campus.thesis'].sudo().search(
            [('student_id', '=', partner.id)],
            order='create_date desc, id desc',
        )
        has_active_thesis = bool(theses.filtered(lambda t: t.state != 'cancelled'))
        is_active_student = bool(partner.is_student and partner.student_status == 'active')
        research_method_passed = partner.sudo()._has_passed_research_method() if partner.is_student else False
        thesis_course_enrolled = partner.sudo()._has_enrolled_thesis_subject() if partner.is_student else False
        if is_active_student and research_method_passed and not has_active_thesis:
            primary_lecturers, co_lecturers = self._get_available_lecturers(partner.program_id)
        else:
            empty_emp = request.env['hr.employee'].sudo().browse()
            primary_lecturers = empty_emp
            co_lecturers = empty_emp

        values = self._prepare_portal_layout_values()
        values.update({
            'theses': theses,
            'has_active_thesis': has_active_thesis,
            'is_active_student': is_active_student,
            'research_method_passed': research_method_passed,
            'thesis_course_enrolled': thesis_course_enrolled,
            'primary_lecturers': primary_lecturers,
            'co_lecturers': co_lecturers,
            'page_name': 'thesis',
            'error': flash['error'],
            'success': flash['success'],
        })
        return request.render('campus_thesis.portal_my_thesis', values)

    @http.route(['/my/thesis/create'], type='http', auth='user', website=True, methods=['POST'])
    @report_errors_to(lambda *args, **kwargs: '/my/thesis')
    def portal_my_thesis_create(self, **post):
        partner = request.env.user.partner_id
        if not partner.is_student or partner.student_status != 'active':
            raise UserError(_("Only active students can register a thesis."))

        title = (post.get('title') or '').strip()
        research_topic = (post.get('research_topic') or '').strip()
        if not title:
            raise ValidationError(_("Thesis title is required."))

        supervisor_id, co_supervisor_id = self._parse_supervisor_ids(post)

        current_year = request.env['academic.year'].sudo()._get_current()
        if not current_year:
            raise UserError(_("No active academic year is configured."))

        thesis = request.env['campus.thesis'].sudo().create({
            'student_id': partner.id,
            'academic_year_id': current_year.id,
            'title': title,
            'research_topic': research_topic,
            'supervisor_id': supervisor_id,
            'co_supervisor_id': co_supervisor_id,
        })
        return _redirect_with_success('/my/thesis/%s' % thesis.id, _("Thesis draft created."))

    @http.route(['/my/thesis/<int:thesis_id>'], type='http', auth='user', website=True, readonly=True)
    def portal_my_thesis_detail(self, thesis_id, **kw):
        thesis = self._get_own_thesis(thesis_id)
        if not thesis:
            return _redirect_with_error('/my/thesis', _("That thesis record is not available."))

        flash = pop_flash_messages()
        partner = request.env.user.partner_id
        if thesis.state in ('draft', 'supervisor_rejected'):
            primary_lecturers, co_lecturers = self._get_available_lecturers(thesis.program_id)
        else:
            empty_emp = request.env['hr.employee'].sudo().browse()
            primary_lecturers = empty_emp
            co_lecturers = empty_emp
        thesis_course_enrolled = (
            partner.sudo()._has_enrolled_thesis_subject()
            if thesis.state == 'proposal_approved'
            else False
        )
        proposal_logs = thesis.progress_line_ids.filtered(lambda l: l.stage == 'proposal')
        thesis_logs = thesis.progress_line_ids.filtered(lambda l: l.stage == 'thesis')

        values = self._prepare_portal_layout_values()
        values.update({
            'thesis': thesis,
            'primary_lecturers': primary_lecturers,
            'co_lecturers': co_lecturers,
            'thesis_course_enrolled': thesis_course_enrolled,
            'proposal_logs': proposal_logs,
            'thesis_logs': thesis_logs,
            'page_name': 'thesis_detail',
            'error': flash['error'],
            'success': flash['success'],
        })
        return request.render('campus_thesis.portal_thesis_detail', values)

    @http.route(['/my/thesis/<int:thesis_id>/update'], type='http', auth='user', website=True, methods=['POST'])
    @report_errors_to(_thesis_page)
    def portal_my_thesis_update(self, thesis_id, **post):
        thesis = self._get_own_thesis(thesis_id)
        if not thesis:
            return _redirect_with_error('/my/thesis', _("That thesis record is not available."))
        self._ensure_active_student(request.env.user.partner_id)

        if thesis.state not in ('draft', 'supervisor_rejected', 'proposal'):
            raise UserError(_("Thesis details can no longer be modified in the current status."))

        title = (post.get('title') or '').strip()
        if not title:
            raise ValidationError(_("Thesis title cannot be empty."))

        vals = {
            'title': title,
            'research_topic': (post.get('research_topic') or '').strip(),
        }
        if thesis.state in ('draft', 'supervisor_rejected'):
            supervisor_id, co_supervisor_id = self._parse_supervisor_ids(post)
            vals.update({
                'supervisor_id': supervisor_id,
                'co_supervisor_id': co_supervisor_id,
            })

        thesis.write(vals)
        return _redirect_with_success('/my/thesis/%s' % thesis.id, _("Thesis details updated."))

    @http.route(['/my/thesis/<int:thesis_id>/submit'], type='http', auth='user', website=True, methods=['POST'])
    @report_errors_to(_thesis_page)
    def portal_my_thesis_submit(self, thesis_id, **post):
        thesis = self._get_own_thesis(thesis_id)
        if not thesis:
            return _redirect_with_error('/my/thesis', _("That thesis record is not available."))
        self._ensure_active_student(request.env.user.partner_id)
        thesis.action_submit_supervisor()
        return _redirect_with_success(
            '/my/thesis/%s' % thesis.id,
            _("Supervision request submitted to your supervisor(s)."),
        )

    @http.route(['/my/thesis/<int:thesis_id>/reset_draft'], type='http', auth='user', website=True, methods=['POST'])
    @report_errors_to(_thesis_page)
    def portal_my_thesis_reset_draft(self, thesis_id, **post):
        thesis = self._get_own_thesis(thesis_id)
        if not thesis:
            return _redirect_with_error('/my/thesis', _("That thesis record is not available."))
        self._ensure_active_student(request.env.user.partner_id)
        if thesis.state != 'supervisor_rejected':
            raise UserError(_(
                "Only rejected supervision requests can be returned to Draft from the student portal."
            ))
        thesis.action_reset_to_draft()
        return _redirect_with_success(
            '/my/thesis/%s' % thesis.id,
            _("Thesis returned to Draft. You may now update your supervisor and resubmit."),
        )

    @http.route(['/my/thesis/<int:thesis_id>/add_progress'], type='http', auth='user', website=True, methods=['POST'])
    @report_errors_to(_thesis_page)
    def portal_my_thesis_add_progress(self, thesis_id, **post):
        thesis = self._get_own_thesis(thesis_id)
        if not thesis:
            return _redirect_with_error('/my/thesis', _("That thesis record is not available."))
        self._ensure_active_student(request.env.user.partner_id)
        if thesis.state not in ('proposal', 'thesis'):
            raise UserError(_("Progress logs can only be added during Proposal or Thesis stages."))
        if len(thesis.progress_line_ids) >= _MAX_PROGRESS_LOGS:
            raise UserError(_(
                "Maximum number of progress logs (%s) reached for this thesis.",
                _MAX_PROGRESS_LOGS,
            ))

        milestone = (post.get('milestone') or '').strip()
        description = (post.get('description') or '').strip()
        if not milestone or not description:
            raise ValidationError(_("Milestone and progress notes are required."))

        try:
            progress_percent = float(post.get('progress_percent') or 0.0)
        except (TypeError, ValueError):
            raise ValidationError(_("Progress percentage must be a valid number."))
        if not math.isfinite(progress_percent) or progress_percent < 0.0 or progress_percent > 100.0:
            raise ValidationError(_("Progress percentage must be between 0 and 100."))

        attachment_data, filename = self._parse_uploaded_file('attachment')
        vals = {
            'thesis_id': thesis.id,
            'stage': thesis.state,
            'milestone': milestone,
            'description': description,
            'progress_percent': progress_percent,
            'state': 'submitted',
        }
        if attachment_data:
            vals['attachment'] = attachment_data
            vals['attachment_filename'] = filename

        request.env['campus.thesis.progress'].sudo().create(vals)
        return _redirect_with_success(
            '/my/thesis/%s' % thesis.id,
            _("Guidance progress log submitted for supervisor review."),
        )

    @http.route(['/my/thesis/<int:thesis_id>/start_thesis'], type='http', auth='user', website=True, methods=['POST'])
    @report_errors_to(_thesis_page)
    def portal_my_thesis_start_thesis(self, thesis_id, **post):
        thesis = self._get_own_thesis(thesis_id)
        if not thesis:
            return _redirect_with_error('/my/thesis', _("That thesis record is not available."))
        self._ensure_active_student(request.env.user.partner_id)
        thesis.action_start_thesis()
        return _redirect_with_success(
            '/my/thesis/%s' % thesis.id,
            _("Thesis course enrollment verified. Welcome to the Thesis Stage!"),
        )

    @http.route(
        ['/my/thesis/<int:thesis_id>/upload_document/<int:doc_id>'],
        type='http', auth='user', website=True, methods=['POST'],
    )
    @report_errors_to(_thesis_page)
    def portal_my_thesis_upload_document(self, thesis_id, doc_id, **post):
        thesis = self._get_own_thesis(thesis_id)
        if not thesis:
            return _redirect_with_error('/my/thesis', _("That thesis record is not available."))
        self._ensure_active_student(request.env.user.partner_id)
        if thesis.state != 'yudisium_docs':
            raise UserError(_("Yudisium documents can only be uploaded during Yudisium Filing."))

        doc = request.env['campus.thesis.document'].sudo().browse(doc_id).exists()
        if not doc or doc.thesis_id != thesis:
            raise UserError(_("That document line does not belong to your thesis."))

        attachment_data, filename = self._parse_uploaded_file('attachment')
        if not attachment_data:
            raise UserError(_("Please choose a file to upload."))

        doc.write({
            'attachment': attachment_data,
            'attachment_filename': filename,
            'submitted_by_student': True,
            'received': False,
        })
        return _redirect_with_success(
            '/my/thesis/%s' % thesis.id,
            _("Document '%s' uploaded and awaiting academic staff verification.") % (filename,),
        )

    @http.route(['/my/thesis/<int:thesis_id>/submit_yudisium'], type='http', auth='user', website=True, methods=['POST'])
    @report_errors_to(_thesis_page)
    def portal_my_thesis_submit_yudisium(self, thesis_id, **post):
        thesis = self._get_own_thesis(thesis_id)
        if not thesis:
            return _redirect_with_error('/my/thesis', _("That thesis record is not available."))
        self._ensure_active_student(request.env.user.partner_id)
        thesis.action_submit_yudisium()
        return _redirect_with_success(
            '/my/thesis/%s' % thesis.id,
            _("Yudisium submitted for sequential approval (Supervisor -> Advisor -> Dean)."),
        )

    @http.route(['/my/thesis/<int:thesis_id>/report'], type='http', auth='user', website=True)
    def portal_my_thesis_report(self, thesis_id, report_type='pdf', download=False, **kw):
        thesis = self._get_own_thesis(thesis_id)
        if not thesis:
            return _redirect_with_error('/my/thesis', _("That thesis record is not available."))
        report_type, download = self._normalize_report_params(report_type, download)
        return self._show_report(
            model=thesis,
            report_type=report_type,
            report_ref='campus_thesis.action_report_thesis',
            download=download,
        )
