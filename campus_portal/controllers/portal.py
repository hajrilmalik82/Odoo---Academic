import logging

from psycopg2 import IntegrityError

from odoo import fields, http, _
from odoo.addons.campus_core.portal_utils import (
    pop_flash_messages,
    redirect_with_error as _redirect_with_error,
    report_errors_to as _shared_report_errors_to,
)
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools import str2bool

_logger = logging.getLogger(__name__)


def report_errors_to(url_for):
    return _shared_report_errors_to(url_for, logger=_logger)


def _krs_page(krs_id, *_args, **_kwargs):
    return '/my/krs/%s' % krs_id


# Module-level, NOT an override of CustomerPortal._items_per_page. That
# attribute is shared by every module that subclasses CustomerPortal - sale,
# account, project - and Odoo merges all of them into one class at runtime, so
# setting it here silently re-paginated every other module's portal lists to 20.
_CAMPUS_ITEMS_PER_PAGE = 20
_ALLOWED_REPORT_TYPES = frozenset({'pdf', 'html'})


class CampusPortal(CustomerPortal):

    def _editable_states(self):
        """The states a student may still change, read from the model.

        One definition: academic.krs._EDITABLE_STATES. Spelled out as a literal
        in three routes, a change to the model would have left them behind.
        """
        return request.env['academic.krs']._EDITABLE_STATES

    # Kept as an alias for any external caller referencing the old name.
    env_editable_states = _editable_states

    def _ensure_active_student(self, partner):
        """Ensure the portal caller is an active student before mutating KRS."""
        if not partner.is_student or partner.student_status != 'active':
            raise UserError(_("Only active students can modify a KRS."))

    def _normalize_report_params(self, report_type, download):
        """Whitelist report_type and parse query-string download flags safely."""
        if report_type not in _ALLOWED_REPORT_TYPES:
            report_type = 'pdf'
        if not isinstance(download, bool):
            download = str2bool(str(download), default=False)
        return report_type, download

    def _ensure_krs_period_open(self, krs):
        """Ensure the academic year's KRS registration window covers today."""
        year = krs.academic_year_id
        today = fields.Date.context_today(krs)
        if not year.active or not year.krs_start_date or not year.krs_end_date:
            raise UserError(_("Academic year KRS period is not configured."))
        if not (year.krs_start_date <= today <= year.krs_end_date):
            raise UserError(_("Current date is outside the allowed KRS period."))

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

    def _offerable_schedule_domain(self, krs):
        """The classes this study plan may actually take.

        One definition, shared by the page that lists them and the route that
        accepts one. The page filtered and the route did not, so a hand-made
        POST could add a section from another programme; it was only refused
        later, by _check_subjects_valid at submission time.

        Mirrors that rule exactly: a subject with no programme is
        university-wide and stays, and a KRS with no programme is not filtered
        at all, because the rule lets those through too. The academic-year
        clause is part of the same definition - a plan may only hold classes
        offered in its own term.
        """
        domain = [('class_id.academic_year_id', '=', krs.academic_year_id.id)]
        if krs.program_id:
            domain += [
                '|',
                ('class_id.subject_id.program_id', '=', False),
                ('class_id.subject_id.program_id', '=', krs.program_id.id),
            ]
        return domain

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
        if not counters:
            # First-semester active students have 0 KRS records; keep the My KRS
            # card visible on /my/home so they can discover and register their
            # first study plan without exposing the card to non-students.
            values['campus_show_krs_onboarding'] = bool(
                partner.is_student
                and partner.student_status == 'active'
                and not request.env['academic.krs'].sudo().search_count([
                    ('student_id', '=', partner.id)
                ])
            )
        return values

    @http.route(['/my/krs', '/my/krs/page/<int:page>'], type='http', auth="user", website=True, readonly=True)
    def portal_my_krs(self, page=1, **kw):
        partner = request.env.user.partner_id
        domain = [('student_id', '=', partner.id)]
        flash = pop_flash_messages()

        # sudo() with the domain pinned to the logged-in partner, the same
        # contract as _get_own_krs and _prepare_home_portal_values. Read ACL on
        # academic.krs is granted to portal, campus staff and lecturers only,
        # so without it this route raised AccessError - a 500 page - for every
        # other internal user. The route is auth="user", not portal-only, so an
        # accountant or a warehouse operator reaches it from /my like anyone
        # else. The counters were fixed for this; the two list pages were not.
        KrsObj = request.env['academic.krs'].sudo()
        total = KrsObj.search_count(domain)
        pager = request.website.pager(
            url='/my/krs',
            total=total,
            page=page,
            step=_CAMPUS_ITEMS_PER_PAGE,
        )
        # academic.year._order is 'name desc, term_type asc, id desc', so
        # ascending on academic_year_id orders newest academic year first.
        krs_records = KrsObj.search(
            domain,
            order='academic_year_id asc, id desc',
            limit=_CAMPUS_ITEMS_PER_PAGE,
            offset=pager['offset'],
        ) if total else KrsObj.browse()

        is_student = bool(partner.is_student)
        can_register_krs = bool(
            is_student
            and partner.student_status == 'active'
            and request.env['academic.year'].sudo()._get_krs_period_open()
        )
        values = self._prepare_portal_layout_values()
        values.update({
            'krs_records': krs_records,
            'pager': pager,
            'page_name': 'krs',
            'default_url': '/my/krs',
            'is_student': is_student,
            'can_register_krs': can_register_krs,
            'error': flash['error'],
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
            return _redirect_with_error('/my/krs', _(
                "Only active students can fill in a KRS.",
            ))

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
        Krs = request.env['academic.krs'].sudo()
        existing_krs = Krs.search([
            ('student_id', '=', partner.id),
            ('academic_year_id', '=', active_year.id),
        ], limit=1)
        if existing_krs:
            return request.redirect('/my/krs/%s' % existing_krs.id)

        # 3. Create it inside a savepoint so a concurrent double-click hitting
        # the unique (student_id, academic_year_id) constraint redirects cleanly
        # to the winning KRS instead of surfacing an error.
        try:
            with request.env.cr.savepoint():
                new_krs = Krs.create({
                    'student_id': partner.id,
                    'academic_year_id': active_year.id,
                })
        except IntegrityError as err:
            if getattr(err, 'pgcode', None) != '23505':
                raise
            existing_krs = Krs.search([
                ('student_id', '=', partner.id),
                ('academic_year_id', '=', active_year.id),
            ], limit=1)
            if existing_krs:
                return request.redirect('/my/krs/%s' % existing_krs.id)
            raise
        return request.redirect('/my/krs/%s' % new_krs.id)

    @http.route(['/my/krs/<int:krs_id>'], type='http', auth="user", website=True, readonly=True)
    def portal_my_krs_detail(self, krs_id, **kw):
        krs = self._get_own_krs(krs_id)
        if not krs:
            return _redirect_with_error('/my/krs', _("That KRS is not available."))

        flash = pop_flash_messages()
        is_editable = krs.state in self._editable_states()
        Schedule = request.env['academic.class.schedule'].sudo()
        # Only load the term schedule catalogue and seat counts when the student
        # can actually add/switch classes; submitted/approved/locked views never
        # render the schedule picker.
        if is_editable:
            available_schedules = Schedule.search(
                self._offerable_schedule_domain(krs), order='class_id, class_code, id',
            )
            enrolled_counts = available_schedules._enrolled_counts()
        else:
            available_schedules = Schedule.browse()
            enrolled_counts = {}

        taken_schedule_ids = set(krs.line_ids.schedule_id.ids)
        scheduled_subject_ids = set(krs.line_ids.filtered('schedule_id').subject_id.ids)
        unscheduled_subject_ids = set(
            krs.line_ids.filtered(lambda line: not line.schedule_id).subject_id.ids
        )
        max_credits = request.env['academic.credit.limit'].sudo()._get_max_credits(
            krs.student_id.cgpa
        )
        values = self._prepare_portal_layout_values()
        values.update({
            'krs': krs,
            'is_editable': is_editable,
            'available_schedules': available_schedules,
            'enrolled_counts': enrolled_counts,
            'taken_schedule_ids': taken_schedule_ids,
            'scheduled_subject_ids': scheduled_subject_ids,
            'unscheduled_subject_ids': unscheduled_subject_ids,
            'max_credits': max_credits,
            'page_name': 'krs_detail',
            'error': flash['error'],
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
            return _redirect_with_error('/my/krs', _("That KRS is not available."))
        report_type, download = self._normalize_report_params(report_type, download)
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

        self._ensure_active_student(request.env.user.partner_id)
        if krs.state not in self._editable_states():
            raise UserError(_("You can only add subjects while the KRS is in Draft or Needs Revision."))
        self._ensure_krs_period_open(krs)

        try:
            schedule_id = int(post.get('schedule_id') or 0)
        except (TypeError, ValueError):
            schedule_id = 0
        Schedule = request.env['academic.class.schedule'].sudo()
        schedule = Schedule.browse(schedule_id).exists()
        if not schedule:
            raise UserError(_("Please choose a valid schedule."))
        # Held to the same list the page itself offers, instead of to the
        # academic year alone. The year check used to be the only one here, so
        # a POST naming a section from another programme was accepted and only
        # refused at submission - after the student had built a whole plan on
        # it. The domain carries the year clause too, so nothing is lost.
        if not Schedule.search_count(
            self._offerable_schedule_domain(krs) + [('id', '=', schedule.id)]
        ):
            raise UserError(_(
                "That class is not offered for your study programme in this "
                "academic year."
            ))

        subject = schedule.class_id.subject_id
        existing_subject_lines = krs.line_ids.filtered(lambda line: line.subject_id == subject)
        if existing_subject_lines.filtered('schedule_id'):
            raise UserError(_(
                "Subject '%s' is already in your KRS. Remove the existing section first if you want to switch classes."
            ) % subject.name)
        unscheduled_line = existing_subject_lines[:1]

        # Advisory capacity check while drafting. Draft lines do not reserve
        # seats (only submitted/approved/locked KRS count), so we intentionally
        # avoid row-locking the schedule here to prevent write contention during
        # peak registration; authoritative locking happens in action_submit().
        capacity = schedule.room_capacity
        taken = schedule._enrolled_count(exclude_krs=krs)
        if capacity <= 0 or taken >= capacity:
            raise UserError(_(
                "Class '%(name)s' is full (%(taken)s / %(capacity)s seats taken)."
            ) % {'name': schedule.display_name, 'taken': taken, 'capacity': capacity})

        for line in krs.line_ids:
            if line == unscheduled_line or not line.schedule_id:
                continue
            existing_sched = line.schedule_id
            if existing_sched._overlaps_with(schedule):
                raise UserError(_(
                    "Schedule overlap detected between %(first)s and %(second)s."
                ) % {'first': schedule.display_name, 'second': existing_sched.display_name})

        if unscheduled_line:
            unscheduled_line.write({'schedule_id': schedule.id})
        else:
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

        self._ensure_active_student(request.env.user.partner_id)
        if krs.state not in self._editable_states():
            raise UserError(_("You can only remove subjects while the KRS is in Draft or Needs Revision."))
        self._ensure_krs_period_open(krs)
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

        self._ensure_active_student(request.env.user.partner_id)
        if krs.state not in self._editable_states():
            raise UserError(_("Only a KRS in Draft or Needs Revision can be submitted."))
        self._ensure_krs_period_open(krs)
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
        flash = pop_flash_messages()

        # sudo() for the same reason as /my/krs above: the domain is pinned to
        # the logged-in partner, so this widens nothing, and without it the
        # page is a 500 for any internal user with no campus group.
        KhsObj = request.env['academic.khs'].sudo()
        total = KhsObj.search_count(domain)
        pager = request.website.pager(
            url='/my/khs',
            total=total,
            page=page,
            step=_CAMPUS_ITEMS_PER_PAGE,
        )
        if total:
            khs_records = KhsObj.search(
                domain,
                order='academic_year_id asc, id desc',
                limit=_CAMPUS_ITEMS_PER_PAGE,
                offset=pager['offset'],
            )
            latest_khs = (
                khs_records[:1]
                if pager['offset'] == 0
                else KhsObj.search(domain, order='academic_year_id asc, id desc', limit=1)
            )
        else:
            khs_records = KhsObj.browse()
            latest_khs = KhsObj.browse()

        values = self._prepare_portal_layout_values()
        values.update({
            'khs_records': khs_records,
            'transcript_khs': latest_khs,
            'pager': pager,
            'page_name': 'khs',
            'default_url': '/my/khs',
            'error': flash['error'],
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
            return _redirect_with_error('/my/khs', _("That KHS is not available."))
        report_type, download = self._normalize_report_params(report_type, download)
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
            return _redirect_with_error('/my/khs', _("That KHS is not available."))
        report_type, download = self._normalize_report_params(report_type, download)
        return self._show_report(
            # The flag is what makes _get_report_base_filename name this a
            # Transcript; without it the download arrives called "KHS - ...",
            # which is the other report printed from the same model.
            model=khs.with_context(campus_transcript_filename=True),
            report_type=report_type,
            report_ref='campus_core.action_report_transcript',
            download=download,
        )
