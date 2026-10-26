from odoo.tests.common import tagged

from .common import CampusCommon


@tagged('post_install', '-at_install')
class TestCampusReports(CampusCommon):
    """The three PDFs, and the one definition behind their filenames.

    A blocker in this history was a translation catalogue that had slipped by
    one entry and broke all three Print buttons in production for months. One
    render per report is what would have caught it on the first upgrade.
    """

    def _locked(self):
        krs = self._make_krs()
        krs.action_submit()
        krs.action_approve()
        krs.action_lock()
        khs = self.env['academic.khs'].search([
            ('student_id', '=', self.student.id),
            ('academic_year_id', '=', self.year.id),
        ], limit=1)
        return krs, khs

    def _render(self, xmlid, records):
        html, _kind = self.env['ir.actions.report']._render_qweb_html(xmlid, records.ids)
        return html.decode() if isinstance(html, bytes) else html

    def test_all_three_reports_render(self):
        krs, khs = self._locked()
        for xmlid, records in (
            ('campus_core.action_report_krs', krs),
            ('campus_core.action_report_khs', khs),
            ('campus_core.action_report_transcript', khs),
        ):
            with self.subTest(report=xmlid):
                self.assertIn(self.student.name, self._render(xmlid, records))

    def test_the_shared_header_and_signatures_are_on_the_documents(self):
        """They were written out verbatim in each file and had already drifted."""
        _krs, khs = self._locked()
        for xmlid in ('campus_core.action_report_khs', 'campus_core.action_report_transcript'):
            body = self._render(xmlid, khs)
            self.assertIn('Student ID (NIM)', body)
            self.assertIn('Head of Study Program', body)
            self.assertIn('Dean of Faculty', body)

    def test_the_transcript_prints_the_configured_grade_scale(self):
        """It used to carry nine hard-coded rows, so editing the scale changed
        the letter grades while the printed legend still stated the old bands."""
        _krs, khs = self._locked()
        body = self._render('campus_core.action_report_transcript', khs)
        for band in self.env['academic.grade.scale']._get_scale_rows():
            self.assertIn(band['letter'], body)

    def test_a_real_zero_is_printed_as_zero_not_as_a_dash(self):
        """0.0 is falsy, so the score column printed "-" while the letter column
        on the same row printed E - the row contradicted itself."""
        _krs, khs = self._locked()
        khs.line_ids[0].write({'numeric_grade': 0.0, 'is_graded': True})
        body = self._render('campus_core.action_report_khs', khs)
        self.assertIn('0.0', body)

    def test_each_report_downloads_under_its_own_name(self):
        """One definition drives the backend Print button and the portal
        download; the transcript used to arrive called "KHS - ..."."""
        krs, khs = self._locked()
        self.assertTrue(krs._get_report_base_filename().startswith('KRS - '))
        khs_name = khs._get_report_base_filename()
        transcript_name = khs.with_context(
            campus_transcript_filename=True,
        )._get_report_base_filename()
        self.assertNotEqual(khs_name, transcript_name)
        self.assertIn(self.student.name, transcript_name)


@tagged('post_install', '-at_install')
class TestTranslatedLabels(CampusCommon):
    """Selection labels that reach a printed document must be translated.

    A display name built from the raw `.selection` attribute returns the list as
    written in the source, so an Indonesian reader saw "(Odd)" on every row of
    an official transcript. _description_selection resolves the catalogue.
    """

    def _in_indonesian(self, record):
        return record.with_context(lang='id_ID').display_name

    def test_the_academic_year_term_is_translated(self):
        if not self.env['res.lang'].search([('code', '=', 'id_ID'), ('active', '=', True)]):
            self.skipTest("id_ID is not installed on this database")
        name = self._in_indonesian(self.year)
        self.assertNotIn('Odd', name, "the term label must not stay in English")
        self.assertIn('Ganjil', name)

    def test_the_schedule_day_is_translated(self):
        if not self.env['res.lang'].search([('code', '=', 'id_ID'), ('active', '=', True)]):
            self.skipTest("id_ID is not installed on this database")
        name = self._in_indonesian(self.schedule)
        self.assertNotIn('Monday', name)
        self.assertIn('Senin', name)

    def test_no_display_name_reads_the_raw_selection(self):
        """The mistake is cheap to repeat, so it is pinned by shape as well.

        `self._fields['x'].selection` is the source list; only
        `_description_selection(env)` goes through the catalogue.
        """
        import inspect
        from odoo.addons.campus_core.models import academic_subject, academic_class_schedule
        for module in (academic_subject, academic_class_schedule):
            source = inspect.getsource(module)
            for line in source.splitlines():
                if '_fields[' in line and '.selection' in line and not line.strip().startswith('#'):
                    self.fail("raw .selection read in %s: %s" % (module.__name__, line.strip()))
