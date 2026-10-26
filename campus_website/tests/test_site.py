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
                self.assertEqual(menu.name, 'Guide')

    def test_the_main_menu_carries_its_indonesian_label(self):
        """The label is record data, not a catalogue term, so i18n export never
        sees it - the id_ID key has to be written by hand or an Indonesian
        reader falls back to the English source."""
        menus = self.env['website.menu'].search([('url', '=', '/')])
        self.assertTrue(menus)
        for menu in menus:
            with self.subTest(website=menu.website_id.name or 'template'):
                self.assertEqual(menu.with_context(lang='id_ID').name, 'Panduan')

    def test_every_website_offers_indonesian_without_defaulting_to_it(self):
        """A frontend page renders in the SITE's language, so id_ID has to be
        among a site's languages to be reachable at all. English stays the
        default: the hook used to replace the list instead of adding to it,
        which left no way back to the language the source is written in."""
        for website in self.env['website'].search([]):
            with self.subTest(website=website.name):
                codes = website.language_ids.mapped('code')
                self.assertIn('id_ID', codes)
                self.assertIn('en_US', codes)
                self.assertEqual(website.default_lang_id.code, 'en_US')

    def test_the_configurator_is_marked_done(self):
        """Otherwise opening the site walks into Odoo's setup wizard."""
        for website in self.env['website'].search([]):
            with self.subTest(website=website.name):
                self.assertTrue(website.configurator_done)
