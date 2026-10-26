import functools
import logging
from urllib.parse import urlencode

from odoo import http, _
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.http import request
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


def _redirect_with_error(url, message):
    return request.redirect('%s?%s' % (url, urlencode({'error': message})))


def report_errors_to(url_for):
    """Turn an exception into a redirect carrying a message the student can read.

    The same four lines used to be copied into every mutating route: a
    ValidationError or UserError is a rule the student can act on and is shown
    as written, anything else is our bug and is logged with a traceback while
    the visitor gets one neutral sentence. Copied four times, a fix to one of
    them reached only one route.

    :param url_for: builds the page to return to out of the route's own arguments.
    """
    def decorator(route):
        @functools.wraps(route)
        def wrapper(self, *args, **kwargs):
            try:
                return route(self, *args, **kwargs)
            except (ValidationError, UserError) as error:
                message = error.args[0] if error.args else _("The action could not be completed.")
                return _redirect_with_error(url_for(*args, **kwargs), message)
            except Exception:
                _logger.exception(
                    "%s failed for user %s", route.__name__, request.env.user.login,
                )
                return _redirect_with_error(url_for(*args, **kwargs), _("A system error occurred."))
        return wrapper
    return decorator


def _krs_page(krs_id, *_args, **_kwargs):
    return '/my/krs/%s' % krs_id


# Module-level, NOT an override of CustomerPortal._items_per_page. That
# attribute is shared by every module that subclasses CustomerPortal - sale,
# account, project - and Odoo merges all of them into one class at runtime, so
# setting it here silently re-paginated every other module's portal lists to 20.
_CAMPUS_ITEMS_PER_PAGE = 20


class CampusPortal(CustomerPortal):

    def env_editable_states(self):
        """The states a student may still change, read from the model.

        One definition: academic.krs._EDITABLE_STATES. Spelled out as a literal
        in three routes, a change to the model would have left them behind.
        """
        return request.env['academic.krs']._EDITABLE_STATES

    def _get_own_krs(self, krs_id):
        """Return the KRS if it belongs to the logged-in student, else empty.

        Portal users hold read-only ACL on academic.krs and academic.krs.line,
        so every change below runs with sudo(). That makes this ownership check
        the only thing standing between a student and someone else's KRS. It
        must stay in front of every mutation, and it must compare partners, not
        trust the id in the URL.
        """
        Krs = request.env['academic.krs']
        partner = request.env.user.partner_id
        krs = Krs.sudo().browse(krs_id).exists()
        if not krs or krs.student_id != partner:
            return Krs.sudo().browse()
        return krs

    def _get_own_khs(self, khs_id):
        """Return the KHS if it belongs to the logged-in student, else empty.

        Same contract as _get_own_krs: the report routes below render with sudo,
        so this ownership check is the only thing between a student and someone
        else's grades.
        """
        Khs = request.env['academic.khs']
        partner = request.env.user.partner_id
        khs = Khs.sudo().browse(khs_id).exists()
        if not khs or khs.student_id != partner:
            return Khs.sudo().browse()
        return khs

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id

        # sudo() with the domain pinned to the logged-in partner, the same
        # contract as _get_own_krs: it counts the caller's own records and
        # nothing else. Read ACL on academic.krs is granted to portal, campus
        # staff and lecturers only, so without sudo this raised AccessError for
        # every other internal user. /my/counters batches up to five counters
        # per call and the client awaits it in willStart, so that single refusal
        # left the whole batch's cards hidden and the portal spinner turning for
        # ever - including cards owned by other modules.
        if 'krs_count' in counters:
            values['krs_count'] = request.env['academic.krs'].sudo().search_count([
                ('student_id', '=', partner.id)
            ])
        if 'khs_count' in counters:
            values['khs_count'] = request.env['academic.khs'].sudo().search_count([
                ('student_id', '=', partner.id)
            ])
        return values

    @http.route(['/my/krs', '/my/krs/page/<int:page>'], type='http', auth="user", website=True, readonly=True)
    def portal_my_krs(self, page=1, **kw):
        partner = request.env.user.partner_id
        domain = [('student_id', '=', partner.id)]

        KrsObj = request.env['academic.krs']
        total = KrsObj.search_count(domain)
        pager = request.website.pager(
            url='/my/krs',
            total=total,
            page=page,
            step=_CAMPUS_ITEMS_PER_PAGE,
        )
        krs_records = KrsObj.search(
            domain,
            limit=_CAMPUS_ITEMS_PER_PAGE,
            offset=pager['offset'],
            order='academic_year_id desc, id desc',
        )

        values = self._prepare_portal_layout_values()
        values.update({
            'krs_records': krs_records,
            'pager': pager,
            'page_name': 'krs',
            'default_url': '/my/krs',
            'error': kw.get('error'),
        })
        return request.render("campus_portal.portal_my_krs", values)

    # POST, not GET. This route CREATES a KRS, and as a GET it was reachable
    # from any link, image or prefetch - no CSRF token involved - so anything
    # that fetched the URL on the student's behalf opened a study plan for them.
    # The template posts a form carrying request.csrf_token().
    @http.route(['/my/krs/register'], type='http', auth="user", website=True, methods=['POST'])
    @report_errors_to(lambda *args, **kwargs: '/my/krs')
    def portal_my_krs_register(self, **kw):
        partner = request.env.user.partner_id

        # Only an active student may hold a KRS. Without this any internal user
        # - an accountant, a warehouse operator - could open /my/krs/register
        # and create a study plan against their own contact, which then failed
        # every submission rule in a way nobody could explain.
        if not partner.is_student or partner.student_status != 'active':
            return request.redirect('/my?' + urlencode({
                'error': _("Only active students can fill in a KRS."),
            }))
        
        # 1. The academic year currently open for registration. Shared definition
        # with campus_pmb, and it also honours `active`, which this inline search
        # did not: an archived year whose dates still covered today was accepted.
        active_year = request.env['academic.year'].sudo()._get_krs_period_open()

        if not active_year:
            return _redirect_with_error('/my/krs', _(
                "The KRS registration period is closed, or no academic year has "
                "been configured."
            ))

        # 2. One study plan per term, whatever state it is in.
        existing_krs = request.env['academic.krs'].search([
            ('student_id', '=', partner.id),
            ('academic_year_id', '=', active_year.id),
        ], limit=1)
        if existing_krs:
            return request.redirect('/my/krs/%s' % existing_krs.id)

        # 3. Create it. sudo() because portal users are read-only on
        # academic.krs; student_id is pinned to the logged-in partner so a
        # visitor cannot open one for someone else, and state is left to its
        # 'draft' default. Errors are turned into a message by the decorator.
        new_krs = request.env['academic.krs'].sudo().create({
            'student_id': partner.id,
            'academic_year_id': active_year.id,
        })
        return request.redirect('/my/krs/%s' % new_krs.id)

    @http.route(['/my/krs/<int:krs_id>'], type='http', auth="user", website=True, readonly=True)
    def portal_my_krs_detail(self, krs_id, **kw):
        krs = self._get_own_krs(krs_id)
        if not krs:
            return request.redirect('/my/krs?' + urlencode({
                'error': _("That KRS is not available."),
            }))

        # Offer only what this student can actually submit. The list used to be
        # every schedule of the academic year, so a student saw sections from
        # other study programmes, pressed Ambil, and only found out at submit
        # time that _check_subjects_valid refuses a subject whose programme is
        # not theirs. The filter mirrors that rule exactly: a subject with no
        # programme is university-wide and stays, and a KRS with no programme
        # is not filtered at all, because the rule lets those through too.
        # That also bounds the query - one programme's offering for one year -
        # where the old one grew with the whole catalogue. No hard limit: a
        # truncated list would silently hide a class the student must take.
        # sudo() so the template can read the advisor from hr.employee without a 403
        schedule_domain = [('class_id.academic_year_id', '=', krs.academic_year_id.id)]
        if krs.program_id:
            schedule_domain += [
                '|',
                ('class_id.subject_id.program_id', '=', False),
                ('class_id.subject_id.program_id', '=', krs.program_id.id),
            ]
        available_schedules = request.env['academic.class.schedule'].sudo().search(
            schedule_domain, order='class_id, class_code, id',
        )
        values = self._prepare_portal_layout_values()
        values.update({
            'krs': krs,
            'available_schedules': available_schedules,
            'page_name': 'krs_detail',
            'error': kw.get('error'),
        })
        return request.render("campus_portal.portal_krs_detail", values)

    @http.route(['/my/krs/<int:krs_id>/report'], type='http', auth="user", website=True)
    def portal_my_krs_report(self, krs_id, report_type='pdf', download=False, **kw):
        """Let a student print their own KRS.

        Rendering goes through CustomerPortal._show_report, which renders with
        ir.actions.report.sudo(). That is what makes it work at all: the KRS
        template prints the academic advisor's name from hr.employee, and portal
        users have no access to that model, nor to hr.employee.public, which Odoo
        grants to base.group_user only. Ownership is established before this by
        _get_own_krs, so sudo here widens nothing the student could not see.
        """
        krs = self._get_own_krs(krs_id)
        if not krs:
            return request.redirect('/my/krs?' + urlencode({
                'error': _("That KRS is not available."),
            }))
        return self._show_report(
            model=krs,
            report_type=report_type,
            report_ref='campus_core.action_report_krs',
            download=download,
        )

    @http.route(['/my/krs/<int:krs_id>/add_line'], type='http', auth="user", website=True, methods=['POST'])
    @report_errors_to(_krs_page)
    def portal_my_krs_add_line(self, krs_id, **post):
        krs = self._get_own_krs(krs_id)
        if not krs:
            return _redirect_with_error('/my/krs', _("That KRS is not available."))

        if krs.state not in self.env_editable_states():
            raise UserError(_("You can only add subjects while the KRS is in Draft or Needs Revision."))

        try:
            schedule_id = int(post.get('schedule_id') or 0)
        except (TypeError, ValueError):
            schedule_id = 0
        schedule = request.env['academic.class.schedule'].sudo().browse(schedule_id).exists()
        if not schedule:
            raise UserError(_("Please choose a valid schedule."))
        if schedule.class_id.academic_year_id != krs.academic_year_id:
            raise UserError(_("That schedule belongs to a different academic year."))

        request.env['academic.krs.line'].sudo().create({
            'krs_id': krs.id,
            'schedule_id': schedule.id,
        })
        return request.redirect('/my/krs/%s' % krs_id)

    @http.route(['/my/krs/<int:krs_id>/delete_line/<int:line_id>'], type='http', auth="user", website=True, methods=['POST'])
    @report_errors_to(_krs_page)
    def portal_my_krs_delete_line(self, krs_id, line_id, **kw):
        krs = self._get_own_krs(krs_id)
        if not krs:
            return _redirect_with_error('/my/krs', _("That KRS is not available."))

        if krs.state not in self.env_editable_states():
            raise UserError(_("You can only remove subjects while the KRS is in Draft or Needs Revision."))
        line = request.env['academic.krs.line'].sudo().browse(line_id).exists()
        if not line or line.krs_id != krs:
            raise UserError(_("That subject is not part of this KRS."))
        line.unlink()
        return request.redirect('/my/krs/%s' % krs_id)

    @http.route(['/my/krs/<int:krs_id>/submit'], type='http', auth="user", website=True, methods=['POST'])
    @report_errors_to(_krs_page)
    def portal_my_krs_submit(self, krs_id, **post):
        krs = self._get_own_krs(krs_id)
        if not krs:
            return _redirect_with_error('/my/krs', _("That KRS is not available."))

        if krs.state not in self.env_editable_states():
            raise UserError(_("This KRS has already been submitted."))
        # sudo() only bypasses access rights. The submission rules are an
        # @api.constrains on academic.krs, so they still run here.
        krs.action_submit()
        return request.redirect('/my/krs/%s' % krs_id)

    # readonly=True on the three pure-read pages only. The report routes are
    # left on a read/write cursor because rendering a report can write an
    # ir.attachment, and the POST routes obviously mutate.
    @http.route(['/my/khs', '/my/khs/page/<int:page>'], type='http', auth="user", website=True, readonly=True)
    def portal_my_khs(self, page=1, **kw):
        partner = request.env.user.partner_id
        domain = [('student_id', '=', partner.id)]

        KhsObj = request.env['academic.khs']
        total = KhsObj.search_count(domain)
        pager = request.website.pager(
            url='/my/khs',
            total=total,
            page=page,
            step=_CAMPUS_ITEMS_PER_PAGE,
        )
        khs_records = KhsObj.search(
            domain,
            limit=_CAMPUS_ITEMS_PER_PAGE,
            offset=pager['offset'],
            order='academic_year_id desc, id desc',
        )

        # The transcript entry point is resolved here, not derived from the
        # paginated list. The template used to link khs_records[0], which is the
        # newest term ON THE CURRENT PAGE - so a student on page 2 printed a
        # transcript keyed off an old semester.
        latest_khs = KhsObj.search(domain, order='academic_year_id desc, id desc', limit=1)

        values = self._prepare_portal_layout_values()
        values.update({
            'khs_records': khs_records,
            'transcript_khs': latest_khs,
            'pager': pager,
            'page_name': 'khs',
            'default_url': '/my/khs',
            # Supplied so the KHS page can show the same error banner the KRS
            # page does; without it a failed ownership check redirected here
            # with a message nothing rendered.
            'error': kw.get('error'),
        })
        return request.render("campus_portal.portal_my_khs", values)

    @http.route(['/my/khs/<int:khs_id>/report'], type='http', auth="user", website=True)
    def portal_my_khs_report(self, khs_id, report_type='pdf', download=False, **kw):
        """Print one term's grade report.

        Rendered through CustomerPortal._show_report, which uses
        ir.actions.report.sudo(). Ownership is settled by _get_own_khs first, so
        sudo widens nothing the student could not already see.
        """
        khs = self._get_own_khs(khs_id)
        if not khs:
            return request.redirect('/my/khs?' + urlencode({
                'error': _("That KHS is not available."),
            }))
        return self._show_report(
            model=khs,
            report_type=report_type,
            report_ref='campus_core.action_report_khs',
            download=download,
        )

    @http.route(['/my/khs/<int:khs_id>/transcript'], type='http', auth="user", website=True)
    def portal_my_khs_transcript(self, khs_id, report_type='pdf', download=False, **kw):
        """Print the cumulative academic transcript.

        The report is bound to academic.khs but reads the student's whole
        history, so any of their own KHS records serves as the entry point.
        """
        khs = self._get_own_khs(khs_id)
        if not khs:
            return request.redirect('/my/khs?' + urlencode({
                'error': _("That KHS is not available."),
            }))
        return self._show_report(
            # The flag is what makes _get_report_base_filename name this a
            # Transcript; without it the download arrives called "KHS - ...",
            # which is the other report printed from the same model.
            model=khs.with_context(campus_transcript_filename=True),
            report_type=report_type,
            report_ref='campus_core.action_report_transcript',
            download=download,
        )
