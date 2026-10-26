from odoo.addons.campus_core import CAMPUS_LANG, _load_campus_translation
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCampusLanguage(TransactionCase):
    """English is the source and the default; Indonesian is a translation.

    The install hook used to write lang on every user and set a default on
    res.partner, so an administrator working in English found their own account
    switched to Indonesian with no setting to point at. These tests pin the
    line between making a language AVAILABLE and imposing it.
    """

    def test_the_hook_activates_indonesian(self):
        """Without this, Odoo skips i18n/*.po entirely - an inactive language
        is never imported - and the catalogue in the repository is dead
        weight."""
        _load_campus_translation(self.env)
        lang = self.env['res.lang'].with_context(active_test=False).search(
            [('code', '=', CAMPUS_LANG)]
        )
        self.assertTrue(lang.active)

    def test_the_hook_leaves_user_languages_alone(self):
        user = self.env['res.users'].create({
            'name': 'ZZTEST Language Keeper',
            'login': 'zztest-language-keeper',
            'lang': 'en_US',
        })
        _load_campus_translation(self.env)
        self.assertEqual(user.lang, 'en_US')

    def test_the_hook_sets_no_default_partner_language(self):
        """Compared against the value already in place rather than asserted to
        be empty: an administrator is free to set one, and the point here is
        only that installing this module is not what put it there."""
        before = self.env['ir.default']._get('res.partner', 'lang')
        _load_campus_translation(self.env)
        self.assertEqual(self.env['ir.default']._get('res.partner', 'lang'), before)

    def test_the_source_strings_are_english(self):
        """A spot check on the rule the whole arrangement rests on. If a label
        is written in Indonesian it renders that way in every language,
        untranslatable, and the catalogue cannot reach it."""
        menu = self.env.ref('campus_core.menu_academic_root')
        self.assertEqual(menu.with_context(lang='en_US').name, 'Academic System')
