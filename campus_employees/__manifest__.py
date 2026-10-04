{
    'name': 'Campus Employees',
    'version': '19.0.1.0.0',
    'summary': 'Academic Profile for Employees (Lecturers)',
    'description': 'Extends HR Employee to include academic profiles and integrates with Campus Core.',
    'category': 'Human Resources',
    'author': 'Hajril Malik',
    # Must NOT depend on campus_pmb: campus_pmb depends on this module.
    # The PMB jurisdiction fields that used to require it now live in campus_pmb.
    'depends': ['base', 'hr', 'campus_core', 'website'],
    'data': [
        'security/campus_security.xml',
        'security/ir.model.access.csv',
        'report/report_krs_templates.xml',
        'views/res_partner_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_job_views.xml',
        'views/website_homepage_employees.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
