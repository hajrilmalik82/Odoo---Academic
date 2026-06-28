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
    'depends': ['base', 'portal', 'campus_core', 'website'],
    'data': [
        'views/portal_templates.xml',
        'views/website_homepage_portal.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
