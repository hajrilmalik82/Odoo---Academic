{
    'name': 'Campus Thesis & Graduation',
    'version': '19.0.1.0.0',
    'summary': 'End-to-End Student Thesis (Skripsi), Yudisium & Graduation Management',
    'description': """
        Manages the complete student thesis lifecycle:
        - Eligibility verification (Research Methodology course passed in KHS)
        - Supervisor selection with Lecturer Approve/Reject workflow
        - Proposal stage with guidance progress logs
        - Thesis stage gated on Thesis course enrollment in an approved/locked KRS
        - Yudisium filing and strict sequential approval (Supervisor -> Academic Advisor -> Dean)
        - Automatic assignment to the nearest open Graduation (Wisuda) schedule
        - Full Student Portal (/my/thesis) & Backend integration
    """,
    'category': 'Education',
    'author': 'Hajril Malik',
    'depends': [
        'mail',
        'hr',
        'campus_core',
        'campus_employees',
        'portal',
        'website',
        'campus_website',
    ],
    'data': [
        'security/thesis_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/mail_activity_type_data.xml',
        'data/thesis_requirement_data.xml',
        'report/report_actions.xml',
        'report/report_thesis_template.xml',
        'wizard/thesis_reject_wizard_views.xml',
        'views/academic_subject_views.xml',
        'views/graduation_schedule_views.xml',
        'views/thesis_requirement_views.xml',
        'views/campus_thesis_views.xml',
        'views/res_partner_views.xml',
        'views/hr_employee_views.xml',
        'views/menus.xml',
        'views/portal_templates.xml',
        'views/website_homepage_thesis.xml',
    ],
    'demo': [
        'demo/campus_demo_thesis.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
