{
    'name': 'Campus PMB (Student Admission)',
    'version': '19.0.1.0.0',
    'summary': 'Penerimaan Mahasiswa Baru (PMB)',
    'description': """
        This module manages new student admissions.
        When a candidate is passed, the system automatically creates their 
        Partner profile and Portal User account.
    """,
    'category': 'Education',
    'author': 'Hajril Malik',
    'depends': ['base', 'mail', 'campus_core', 'portal', 'website', 'campus_employees'],
    'data': [
        'security/pmb_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/mail_activity_type_data.xml',
        'views/website_admission_templates.xml',
        'views/website_homepage_pmb.xml',
        'views/admission_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
