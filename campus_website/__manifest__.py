{
    'name': 'Campus Website',
    'version': '19.0.1.0.0',
    'summary': 'Public site, login panel and documentation for the campus suite',
    'description': """
        Everything the campus suite puts on the public website: the chrome
        (header, footer, copyright), the login panel, the documentation page,
        and the one-off setup that skips Odoo's website configurator.

        It exists so campus_core does not have to. A core module carries the
        academic domain - faculties, study plans, grades - and should install on
        a database that has no website at all. Keeping these templates there
        forced 'website' into its dependencies for reasons that had nothing to
        do with academics.
    """,
    'category': 'Education',
    'author': 'Hajril Malik',
    'depends': ['campus_core', 'website'],
    'data': [
        'data/website_configurator_bypass.xml',
        'views/website_homepage_core.xml',
        'views/website_layout_core.xml',
        'views/website_login_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'campus_website/static/src/scss/campus_website.scss',
            'campus_website/static/src/js/campus_website.js',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
