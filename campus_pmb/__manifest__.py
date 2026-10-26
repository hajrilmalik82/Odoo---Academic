{
    'name': 'Campus PMB (Student Admission)',
    'version': '19.0.1.3.0',
    'summary': 'Penerimaan Mahasiswa Baru (PMB)',
    'description': """
        This module manages new student admissions.
        When a candidate is passed, the system automatically creates their 
        Partner profile and Portal User account.
    """,
    'category': 'Education',
    'author': 'Hajril Malik',
    # 'hr' is direct now: this module extends hr.employee with the PMB
    # jurisdiction fields. 'campus_employees' supplies academic_role.
    # 'portal' dropped: nothing in this module inherits a portal model,
    # extends portal templates or uses CustomerPortal - campus_portal is the
    # module that does. 'base' dropped: every module depends on it implicitly.
    # 'website' stays: this module serves the public admission form itself.
    # campus_website is added because its documentation page inherits a
    # template that module owns.
    'depends': ['mail', 'hr', 'campus_core', 'website', 'campus_website', 'campus_employees'],
    'data': [
        'security/pmb_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/mail_activity_type_data.xml',
        'data/admission_requirement_data.xml',
        'views/hr_employee_views.xml',
        'views/website_admission_templates.xml',
        'views/website_homepage_pmb.xml',
        'views/admission_views.xml',
        'views/admission_requirement_views.xml',
    ],
    'demo': [
        'demo/campus_demo_admissions.xml',
    ],
    'installable': True,
    # campus_core is the single app tile for this suite; campus_pmb,
    # campus_employees and campus_portal are parts of it, not separate apps.
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
