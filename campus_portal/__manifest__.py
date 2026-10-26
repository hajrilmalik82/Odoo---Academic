{
    'name': 'Campus Portal',
    'version': '19.0.1.0.0',
    'summary': 'Student Portal for KRS and KHS',
    'description': """
        This module provides a frontend portal for students to view their 
        Course Packages (KRS) and Academic Transcripts (KHS).
    """,
    'category': 'Education',
    'author': 'Hajril Malik',
    # 'website' stays: the /my pages are website=True routes. campus_website
    # is added because the documentation page inherits a template it owns.
    'depends': ['portal', 'campus_core', 'website', 'campus_website'],
    'data': [
        'views/portal_templates.xml',
        'views/website_homepage_portal.xml',
    ],
    'demo': [
        'demo/campus_demo_portal_users.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
