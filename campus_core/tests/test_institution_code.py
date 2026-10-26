from psycopg2.errors import UniqueViolation

from odoo.exceptions import ValidationError
from odoo.tests.common import tagged
from odoo.tools import mute_logger

from .common import TAG, CampusCommon
from ..models.academic_institution import _derive_code


@tagged('post_install', '-at_install')
class TestInstitutionCode(CampusCommon):
    """academic.faculty.code and academic.program.code: the NIM prefix.

    The prefix used to be the initials of the CURRENT display name, so renaming
    a faculty silently started a new numbering series for every student admitted
    afterwards. These pin the replacement.
    """

    def _nim(self, faculty=None, program=None):
        return self.env['campus.admission']._generate_nim(
            faculty or self.faculty, program or self.program, self.year,
        )[0]

    def test_derivation_matches_the_old_nim_prefix(self):
        """The seed reproduces exactly what the old name-based prefix produced.

        That is what lets an existing campus keep its numbering series across
        the upgrade instead of starting a new one.
        """
        self.assertEqual(_derive_code('Teknik Informatika'), 'TI')
        self.assertEqual(_derive_code('Fakultas Teknologi Industri'), 'FT')
        self.assertEqual(_derive_code('Hukum'), 'H')
        self.assertEqual(_derive_code(''), 'XX')
        self.assertEqual(_derive_code(None), 'XX')

    def test_code_is_seeded_on_create_when_not_given(self):
        program = self.env['academic.program'].create({
            'name': '%s Sistem Informasi' % TAG,
            'faculty_id': self.faculty.id,
        })
        self.assertTrue(program.code, "a programme must never be left without a code")
        self.assertEqual(program.code, _derive_code('%s Sistem Informasi' % TAG))

    def test_an_explicit_code_is_kept(self):
        program = self.env['academic.program'].create({
            'name': '%s Teknik Mesin' % TAG,
            'code': 'TM',
            'faculty_id': self.faculty.id,
        })
        self.assertEqual(program.code, 'TM')

    def test_renaming_does_not_move_the_nim_prefix(self):
        before = self._nim()
        self.faculty.name = '%s Fakultas Teknologi Industri' % TAG
        self.program.name = '%s Teknik Informatika dan Komputer' % TAG
        after = self._nim()
        self.assertEqual(
            before.rsplit('-', 1)[0], after.rsplit('-', 1)[0],
            "renaming a faculty or programme must not change the NIM prefix",
        )

    def test_code_is_locked_once_a_nim_has_been_issued(self):
        self.env['res.partner'].create({
            'name': '%s Mahasiswa Ber-NIM' % TAG,
            'is_student': True,
            'nim': '%s-0001' % TAG,
            'program_id': self.program.id,
        })
        with self.assertRaises(ValidationError):
            self.program.code = 'ZZ'

    def test_code_may_still_be_corrected_before_any_nim(self):
        program = self.env['academic.program'].create({
            'name': '%s Teknik Industri' % TAG,
            'faculty_id': self.faculty.id,
            'code': 'ZTI',
        })
        program.code = 'ZTD'
        self.assertEqual(program.code, 'ZTD')

    def test_two_programmes_cannot_share_a_code(self):
        """Without this, two programmes under one faculty produce the same NIM.

        'Teknik Informatika' and 'Teknik Industri' both reduce to TI, so the
        automatic derivation collides on exactly the pair a real campus has.
        """
        # savepoint() so the failed INSERT does not poison the test transaction.
        with mute_logger('odoo.sql_db'), self.assertRaises(UniqueViolation), self.cr.savepoint():
            self.env['academic.program'].create({
                'name': '%s Teknik Industri Lain' % TAG,
                'faculty_id': self.faculty.id,
                'code': self.program.code,
            })
            self.env.flush_all()

    def test_the_same_code_is_refused_whatever_the_case(self):
        with mute_logger('odoo.sql_db'), self.assertRaises(UniqueViolation), self.cr.savepoint():
            self.env['academic.program'].create({
                'name': '%s Huruf Kecil' % TAG,
                'faculty_id': self.faculty.id,
                'code': self.program.code.lower(),
            })
            self.env.flush_all()


@tagged('post_install', '-at_install')
class TestMirroredDepartments(CampusCommon):
    """academic.faculty and academic.program each keep an hr.department in step.

    The sync is one-directional, so an HR manager editing the mirrored
    department left the two representations disagreeing with nothing to detect
    it. These pin the guard that closes that.
    """

    def test_a_faculty_gets_a_mirrored_department(self):
        self.assertTrue(self.faculty.department_id)
        self.assertEqual(self.faculty.department_id.name, self.faculty.name)

    def test_renaming_the_faculty_still_reaches_the_department(self):
        """The guard must not block the sync it exists to protect."""
        self.faculty.name = '%s Fakultas Berganti Nama' % TAG
        self.assertEqual(self.faculty.department_id.name, self.faculty.name)

    def test_the_department_cannot_be_renamed_from_hr(self):
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            self.faculty.department_id.write({'name': 'Diubah dari HR'})

    def test_the_department_cannot_be_deleted_from_hr(self):
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            self.faculty.department_id.unlink()

    def test_deleting_the_faculty_takes_its_department_with_it(self):
        faculty = self.env['academic.faculty'].create({
            'name': '%s Fakultas Sementara' % TAG, 'code': 'ZFM',
        })
        department = faculty.department_id
        self.assertTrue(department)
        faculty.unlink()
        self.assertFalse(department.exists())

    def test_an_ordinary_department_is_untouched(self):
        """Only mirrored ones are guarded; HR keeps working normally."""
        department = self.env['hr.department'].create({'name': '%s Keuangan' % TAG})
        department.name = '%s Keuangan dan Akuntansi' % TAG
        self.assertEqual(department.name, '%s Keuangan dan Akuntansi' % TAG)
        department.unlink()
