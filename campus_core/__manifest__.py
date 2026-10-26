{
    'name': 'Campus academic',
    'version': '19.0.1.0.0',
    'summary': 'Core Module for University ERP (SIAKAD)',
    'description': 'Master Facilities, Institutions, KRS Management, and Smart Scheduling.',
    'category': 'Education',
    'author': 'Hajril Malik',
    # No 'website' here on purpose. A core module carries the academic domain
    # and installs on a database that has no website at all; everything this
    # suite puts on the public site lives in campus_website.
    'depends': ['base', 'hr', 'mail'],
    'data': [
        'security/campus_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/academic_credit_limit_data.xml',
        'data/academic_grade_scale_data.xml',
        'data/mail_activity_type_data.xml',
        'report/report_actions.xml',
        'report/report_campus_common.xml',
        'report/report_krs_template.xml',
        'report/report_khs_template.xml',
        'report/report_transcript_template.xml',
        'wizard/krs_generator_wizard_views.xml',
        'wizard/assign_schedule_wizard_views.xml',
        'views/res_partner_views.xml',
        'views/hr_department_views.xml',
        'views/campus_facility_views.xml',
        'views/academic_institution_views.xml',
        'views/academic_krs_views.xml',
        'views/academic_course_package_views.xml',
        'views/academic_khs_views.xml',
        'views/academic_class_views.xml',
        'views/academic_class_schedule_views.xml',
        'views/menus.xml',
        # After menus.xml: the credit-limit menu hangs off menu_academic_configuration,
        # and the settings view links to the credit-limit action.
        'views/academic_credit_limit_views.xml',
        'views/academic_grade_scale_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'demo': [
        'demo/campus_demo_master.xml',
        'demo/campus_demo_curriculum.xml',
        'demo/campus_demo_people.xml',
        'demo/campus_demo_classes.xml',
        'demo/campus_demo_study_plans.xml',
    ],
    # Indonesian is asked for explicitly now that the source strings are
    # English; see _set_campus_language in __init__.py. The WEBSITE's language
    # is set by campus_website, which is the module that owns the site.
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
