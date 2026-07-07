from odoo import http, _
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.http import request
from odoo.exceptions import ValidationError, UserError


class CampusPortal(CustomerPortal):
    _items_per_page = 20

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
        from odoo import fields
        today = fields.Date.context_today(request.env.user)
        active_year = request.env['academic.year'].search([
            ('krs_start_date', '<=', today),
            ('krs_end_date', '>=', today)
        ], limit=1)
        
        if not active_year:
            return request.redirect('/my/krs?error=Masa pengisian KRS sedang ditutup atau Tahun Akademik belum diatur.')
            
        # 2. Prevent duplicate: Find existing KRS for this term regardless of state
        existing_krs = request.env['academic.krs'].search([
            ('student_id', '=', partner.id),
            ('academic_year_id', '=', active_year.id)
        ], limit=1)
        
        if existing_krs:
            return request.redirect('/my/krs/%s' % existing_krs.id)
            
        # 3. Create a new KRS automatically
        try:
            new_krs = request.env['academic.krs'].create({
                'student_id': partner.id,
                'academic_year_id': active_year.id,
            })
            return request.redirect('/my/krs/%s' % new_krs.id)
        except Exception as e:
            return request.redirect('/my/krs?error=%s' % str(e))

    @http.route(['/my/krs/<int:krs_id>'], type='http', auth="user", website=True)
    def portal_my_krs_detail(self, krs_id, **kw):
        try:
            krs = request.env['academic.krs'].browse(krs_id)
            krs.check_access_rights('read')
            krs.check_access_rule('read')
        except Exception:
            return request.redirect('/my/krs')

        available_schedules = request.env['academic.class.schedule'].search([
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
        try:
            krs = request.env['academic.krs'].browse(krs_id)
            krs.check_access_rule('write')
            if krs.state != 'draft':
                raise UserError(_("You can only add subjects to a draft KRS."))
            
            request.env['academic.krs.line'].create({
                'krs_id': krs.id,
                'schedule_id': int(post.get('schedule_id')),
            })
        except Exception as e:
            return request.redirect('/my/krs/%s?error=%s' % (krs_id, str(e)))
        return request.redirect('/my/krs/%s' % krs_id)

    @http.route(['/my/krs/<int:krs_id>/delete_line/<int:line_id>'], type='http', auth="user", website=True)
    def portal_my_krs_delete_line(self, krs_id, line_id, **kw):
        try:
            krs = request.env['academic.krs'].browse(krs_id)
            krs.check_access_rule('write')
            if krs.state == 'draft':
                line = request.env['academic.krs.line'].browse(line_id)
                if line.krs_id.id == krs.id:
                    line.unlink()
        except Exception as e:
            return request.redirect('/my/krs/%s?error=%s' % (krs_id, str(e)))
        return request.redirect('/my/krs/%s' % krs_id)

    @http.route(['/my/krs/<int:krs_id>/submit'], type='http', auth="user", website=True, methods=['POST'])
    def portal_my_krs_submit(self, krs_id, **post):
        try:
            krs = request.env['academic.krs'].browse(krs_id)
            krs.check_access_rule('write')
            if krs.state in ('draft', 'revision'):
                krs.action_submit()
        except Exception as e:
            return request.redirect('/my/krs/%s?error=%s' % (krs_id, str(e)))
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
