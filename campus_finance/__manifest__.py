{
    'name': 'Campus Finance',
    'version': '1.0',
    'category': 'Education',
    'summary': 'Finance Integration for Campus Management',
    'description': """
        Handles billing, invoicing, and payment integration for PMB and Students.
    """,
    'author': 'Campus',
    'depends': ['campus_pmb', 'account', 'payment', 'website_payment'],
    'data': [
        'security/finance_security.xml',
        'views/admission_finance_views.xml',
        'views/res_config_settings_views.xml',
        'views/website_homepage_finance.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
