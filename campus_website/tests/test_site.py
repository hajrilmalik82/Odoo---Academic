from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestCampusSite(HttpCase):
    """The public site: the pages render, and the chrome is what it claims.

    These are cheap and they close the gap that let a rename sit broken: the
    declarative one reached a menu nobody sees while a line of JavaScript
    renamed the visible one, so deleting the JavaScript silently undid it.
    """

    def test_the_homepage_renders(self):
        response = self.url_open('/')
        self.assertEqual(response.status_code, 200)

    def test_the_homepage_keeps_an_editor_drop_zone(self):
        """oe_structure is what the Website Builder saves blocks into.
        Replacing the stock wrap outright removed it, and Edit on / then had
        nowhere to put anything."""
        self.assertIn('oe_structure', self.url_open('/').text)

    def test_the_login_page_renders(self):
        self.assertEqual(self.url_open('/web/login').status_code, 200)

    def test_the_main_menu_is_renamed_on_every_website(self):
        """The xmlid website.menu_home is the TEMPLATE menu, website_id False.
        Each website holds its own copy, and that copy is what the header
        renders - so a rename that only touches the template is invisible."""
        menus = self.env['website.menu'].search([('url', '=', '/')])
        self.assertTrue(menus)
        for menu in menus:
            with self.subTest(website=menu.website_id.name or 'template'):
                self.assertEqual(menu.name, 'Panduan')

    def test_the_configurator_is_marked_done(self):
        """Otherwise opening the site walks into Odoo's setup wizard."""
        for website in self.env['website'].search([]):
            with self.subTest(website=website.name):
                self.assertTrue(website.configurator_done)
