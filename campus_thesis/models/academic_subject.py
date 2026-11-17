from odoo import fields, models


class AcademicSubject(models.Model):
    """Classify curriculum subjects that gate the thesis lifecycle.

    A university's Research Methodology and Thesis courses can carry different
    titles across study programmes ("Metodologi Penelitian", "Metode Riset",
    "Skripsi", "Tugas Akhir"), so matching on the name string would break
    silently. Marking the role here keeps the curriculum decoupled and lets each
    programme designate its own gating courses cleanly.
    """

    _inherit = 'academic.subject'

    thesis_role = fields.Selection([
        ('regular', 'Regular Subject'),
        ('research_method', 'Research Methodology'),
        ('thesis', 'Thesis / Final Project'),
    ], string='Thesis Classification', default='regular', required=True, index=True,
       help="Marks subjects that gate the thesis workflow: passing Research "
            "Methodology unlocks thesis registration; enrolling in Thesis unlocks "
            "the thesis writing stage after proposal approval.")
