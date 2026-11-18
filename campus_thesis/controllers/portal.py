import base64
import functools
import logging
import math
import os
from urllib.parse import urlencode

from odoo import http, _
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB safety cap


def _redirect_with_error(url, message):
    return request.redirect('%s?%s' % (url, urlencode({'error': message})))


def _redirect_with_success(url, message):
    return request.redirect('%s?%s' % (url, urlencode({'success': message})))


def report_errors_to(url_for):
    """Turn ValidationError/UserError into a readable banner on redirect."""
    def decorator(route):
        @functools.wraps(route)
        def wrapper(self, *args, **kwargs):
            try:
                with request.env.cr.savepoint():
                    return route(self, *args, **kwargs)
            except (ValidationError, UserError, AccessError) as error:
                message = error.args[0] if error.args else _("The action could not be completed.")
                return _redirect_with_error(url_for(*args, **kwargs), message)
            except Exception:
                _logger.exception(
                    "%s failed for user %s", route.__name__, request.env.user.login,
                )
                return _redirect_with_error(url_for(*args, **kwargs), _("A system error occurred."))
        return wrapper
    return decorator


def _thesis_page(thesis_id, *_args, **_kwargs):
    return '/my/thesis/%s' % thesis_id


class CampusThesisPortal(CustomerPortal):

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

    def _get_available_lecturers(self, partner):
        Lecturer = request.env['hr.employee'].sudo()
        primary_domain = [('academic_role', '=', 'lecturer')]
        if partner.program_id:
            primary_domain.append(('program_id', '=', partner.program_id.id))
        else:
            primary_domain.append((0, '=', 1))
        primary_lecturers = Lecturer.search(primary_domain, order='name')
        co_lecturers = Lecturer.search([('academic_role', '=', 'lecturer')], order='name')
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

    def _parse_uploaded_file(self, field_name='attachment'):
        upload = request.httprequest.files.get(field_name)
        if not upload or not upload.filename:
            return None, None
        raw = upload.read(_MAX_UPLOAD_BYTES + 1)
        if len(raw) > _MAX_UPLOAD_BYTES:
            raise UserError(_("Uploaded file must not exceed 10 MB."))
        if not raw:
            raise UserError(_("Uploaded file is empty."))
        filename = os.path.basename(upload.filename)
        return base64.b64encode(raw), filename

    @http.route(['/my/thesis'], type='http', auth='user', website=True, readonly=True)
    def portal_my_thesis(self, **kw):
        partner = request.env.user.partner_id
        theses = request.env['campus.thesis'].sudo().search(
            [('student_id', '=', partner.id)],
            order='create_date desc, id desc',
        )
        has_active_thesis = bool(theses.filtered(lambda t: t.state != 'cancelled'))
        is_active_student = bool(partner.is_student and partner.student_status == 'active')
        research_method_passed = partner.sudo()._has_passed_research_method() if partner.is_student else False
        thesis_course_enrolled = partner.sudo()._has_enrolled_thesis_subject() if partner.is_student else False
        if is_active_student and research_method_passed and not has_active_thesis:
            primary_lecturers, co_lecturers = self._get_available_lecturers(partner)
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
            'lecturers': primary_lecturers,
            'page_name': 'thesis',
            'error': kw.get('error'),
            'success': kw.get('success'),
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

        partner = request.env.user.partner_id
        primary_lecturers, co_lecturers = self._get_available_lecturers(partner)
        research_method_passed = partner.sudo()._has_passed_research_method()
        thesis_course_enrolled = partner.sudo()._has_enrolled_thesis_subject()
        nearest_graduation = (
            thesis.graduation_id
            or request.env['campus.graduation.schedule'].sudo()._get_nearest_schedule()
        )
        proposal_logs = thesis.progress_line_ids.filtered(lambda l: l.stage == 'proposal')
        thesis_logs = thesis.progress_line_ids.filtered(lambda l: l.stage == 'thesis')

        values = self._prepare_portal_layout_values()
        values.update({
            'thesis': thesis,
            'primary_lecturers': primary_lecturers,
            'co_lecturers': co_lecturers,
            'lecturers': primary_lecturers,
            'research_method_passed': research_method_passed,
            'thesis_course_enrolled': thesis_course_enrolled,
            'nearest_graduation': nearest_graduation,
            'proposal_logs': proposal_logs,
            'thesis_logs': thesis_logs,
            'page_name': 'thesis_detail',
            'error': kw.get('error'),
            'success': kw.get('success'),
        })
        return request.render('campus_thesis.portal_thesis_detail', values)

    @http.route(['/my/thesis/<int:thesis_id>/update'], type='http', auth='user', website=True, methods=['POST'])
    @report_errors_to(_thesis_page)
    def portal_my_thesis_update(self, thesis_id, **post):
        thesis = self._get_own_thesis(thesis_id)
        if not thesis:
            return _redirect_with_error('/my/thesis', _("That thesis record is not available."))

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
        if thesis.state not in ('proposal', 'thesis'):
            raise UserError(_("Progress logs can only be added during Proposal or Thesis stages."))

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
            'note': (post.get('note') or doc.note or '').strip(),
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
        return self._show_report(
            model=thesis,
            report_type=report_type,
            report_ref='campus_thesis.action_report_thesis',
            download=download,
        )
