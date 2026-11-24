from odoo.tests.common import tagged

from odoo.addons.campus_core.tests.common import TAG, CampusHttpCommon


@tagged('post_install', '-at_install', 'campus_ui')
class TestCampusWebsiteUiTours(CampusHttpCommon):
    """Comprehensive browser UI tours for campus_website homepage, login, and portal entry."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ui_user = cls.env['res.users'].create({
            'name': '%s Website UI User' % TAG,
            'login': 'zz.ui.website@contoh.test',
            'password': 'zz-ui-password',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.portal_ui_user = cls.env['res.users'].create({
            'name': '%s Website Portal UI User' % TAG,
            'login': 'zz.ui.portal.web@contoh.test',
            'password': 'zz-ui-password',
            'group_ids': [(6, 0, [cls.env.ref('base.group_portal').id])],
        })

    def test_01_website_login_ui_tour(self):
        self.start_tour('/web/login', 'campus_website_ui_tour')

    def test_02_portal_user_login_redirects_to_portal_ui_tour(self):
        self.start_tour('/web/login', 'campus_website_portal_login_ui_tour')

    def test_03_public_homepage_core_tab_and_layout_ui_tour(self):
        self.start_tour('/', 'campus_website_homepage_ui_tour')
