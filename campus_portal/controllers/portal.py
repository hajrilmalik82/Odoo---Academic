import logging
from urllib.parse import urlencode

from odoo import http, _, fields
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.http import request
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class CampusPortal(CustomerPortal):
    _items_per_page = 20

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

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id

        if 'krs_count' in counters:
            values['krs_count'] = request.env['academic.krs'].search_count([
                ('student_id', '=', partner.id)
            ])
        if 'khs_count' in counters:
            values['khs_count'] = request.env['academic.khs'].search_count([
                ('student_id', '=', partner.id)
            ])
        return values

    @http.route(['/my/krs', '/my/krs/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_krs(self, page=1, **kw):
        partner = request.env.user.partner_id
        domain = [('student_id', '=', partner.id)]

        KrsObj = request.env['academic.krs']
        total = KrsObj.search_count(domain)
        pager = request.website.pager(
            url='/my/krs',
            total=total,
            page=page,
            step=self._items_per_page,
        )
        krs_records = KrsObj.search(
            domain,
            limit=self._items_per_page,
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

    @http.route(['/my/krs/register'], type='http', auth="user", website=True)
    def portal_my_krs_register(self, **kw):
        partner = request.env.user.partner_id
        
        # 1. Find Active Academic Year based on KRS Period
        today = fields.Date.context_today(request.env.user)
        active_year = request.env['academic.year'].search([
            ('krs_start_date', '<=', today),
            ('krs_end_date', '>=', today)
        ], limit=1)
        
        if not active_year:
            return request.redirect('/my/krs?' + urlencode({
                'error': _("Masa pengisian KRS sedang ditutup atau Tahun Akademik belum diatur."),
            }))
            
        # 2. Prevent duplicate: Find existing KRS for this term regardless of state
        existing_krs = request.env['academic.krs'].search([
            ('student_id', '=', partner.id),
            ('academic_year_id', '=', active_year.id)
        ], limit=1)
        
        if existing_krs:
            return request.redirect('/my/krs/%s' % existing_krs.id)
            
        # 3. Create a new KRS automatically.
        # sudo() because portal users are read-only on academic.krs; student_id
        # is pinned to the logged-in partner so a visitor cannot create a KRS
        # for someone else, and state is left to its 'draft' default.
        try:
            new_krs = request.env['academic.krs'].sudo().create({
                'student_id': partner.id,
                'academic_year_id': active_year.id,
            })
            return request.redirect('/my/krs/%s' % new_krs.id)
        except (ValidationError, UserError) as e:
            return request.redirect('/my/krs?' + urlencode({'error': e.args[0]}))
        except Exception:
            _logger.exception("KRS register failed for user %s", request.env.user.login)
            return request.redirect('/my/krs?' + urlencode({'error': _("Terjadi kesalahan sistem.")}))

    @http.route(['/my/krs/<int:krs_id>'], type='http', auth="user", website=True)
    def portal_my_krs_detail(self, krs_id, **kw):
        krs = self._get_own_krs(krs_id)
        if not krs:
            return request.redirect('/my/krs')

        # sudo() so the template can read the advisor from hr.employee without a 403
        available_schedules = request.env['academic.class.schedule'].sudo().search([
            ('class_id.academic_year_id', '=', krs.academic_year_id.id)
        ])
        values = self._prepare_portal_layout_values()
        values.update({
            'krs': krs,
            'available_schedules': available_schedules,
            'page_name': 'krs_detail',
            'error': kw.get('error'),
        })
        return request.render("campus_portal.portal_krs_detail", values)

    @http.route(['/my/krs/<int:krs_id>/add_line'], type='http', auth="user", website=True, methods=['POST'])
    def portal_my_krs_add_line(self, krs_id, **post):
        krs = self._get_own_krs(krs_id)
        if not krs:
            return request.redirect('/my/krs')
        try:
            if krs.state not in ('draft', 'revision'):
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
        except (ValidationError, UserError) as e:
            return request.redirect('/my/krs/%s?%s' % (krs_id, urlencode({'error': e.args[0]})))
        except Exception:
            _logger.exception("KRS add_line failed for user %s", request.env.user.login)
            return request.redirect('/my/krs/%s?%s' % (krs_id, urlencode({'error': _("Terjadi kesalahan sistem.")})))
        return request.redirect('/my/krs/%s' % krs_id)

    @http.route(['/my/krs/<int:krs_id>/delete_line/<int:line_id>'], type='http', auth="user", website=True, methods=['POST'])
    def portal_my_krs_delete_line(self, krs_id, line_id, **kw):
        krs = self._get_own_krs(krs_id)
        if not krs:
            return request.redirect('/my/krs')
        try:
            if krs.state not in ('draft', 'revision'):
                raise UserError(_("You can only remove subjects while the KRS is in Draft or Needs Revision."))
            line = request.env['academic.krs.line'].sudo().browse(line_id).exists()
            if not line or line.krs_id != krs:
                raise UserError(_("That subject is not part of this KRS."))
            line.unlink()
        except (ValidationError, UserError) as e:
            return request.redirect('/my/krs/%s?%s' % (krs_id, urlencode({'error': e.args[0]})))
        except Exception:
            _logger.exception("KRS delete_line failed for user %s", request.env.user.login)
            return request.redirect('/my/krs/%s?%s' % (krs_id, urlencode({'error': _("Terjadi kesalahan sistem.")})))
        return request.redirect('/my/krs/%s' % krs_id)

    @http.route(['/my/krs/<int:krs_id>/submit'], type='http', auth="user", website=True, methods=['POST'])
    def portal_my_krs_submit(self, krs_id, **post):
        krs = self._get_own_krs(krs_id)
        if not krs:
            return request.redirect('/my/krs')
        try:
            if krs.state not in ('draft', 'revision'):
                raise UserError(_("This KRS has already been submitted."))
            # sudo() only bypasses access rights. The nine submission rules are
            # an @api.constrains on academic.krs, so they still run here.
            krs.action_submit()
        except (ValidationError, UserError) as e:
            return request.redirect('/my/krs/%s?%s' % (krs_id, urlencode({'error': e.args[0]})))
        except Exception:
            _logger.exception("KRS submit failed for user %s", request.env.user.login)
            return request.redirect('/my/krs/%s?%s' % (krs_id, urlencode({'error': _("Terjadi kesalahan sistem.")})))
        return request.redirect('/my/krs/%s' % krs_id)

    @http.route(['/my/khs', '/my/khs/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_khs(self, page=1, **kw):
        partner = request.env.user.partner_id
        domain = [('student_id', '=', partner.id)]

        KhsObj = request.env['academic.khs']
        total = KhsObj.search_count(domain)
        pager = request.website.pager(
            url='/my/khs',
            total=total,
            page=page,
            step=self._items_per_page,
        )
        khs_records = KhsObj.search(
            domain,
            limit=self._items_per_page,
            offset=pager['offset'],
            order='academic_year_id desc, id desc',
        )

        values = self._prepare_portal_layout_values()
        values.update({
            'khs_records': khs_records,
            'pager': pager,
            'page_name': 'khs',
            'default_url': '/my/khs',
        })
        return request.render("campus_portal.portal_my_khs", values)
