# Laporan Audit & Skenario Uji — `Odoo---Academic`

> **Cakupan:** 6 modul aktif (`campus_core`, `campus_employees`, `campus_pmb`, `campus_portal`, `campus_thesis`, `campus_website`) dan `jalankan-test.sh` pada commit `ec6ebf4`.  
> **Dikecualikan:** `login_as_any_user` dan `web_responsive`.

---

## Ringkasan Status

### A. Temuan yang Sudah Diperbaiki (Terverifikasi di Kode)

| Kode | Ringkasan Perbaikan | Commit | Lokasi Verifikasi |
| :---: | :--- | :---: | :--- |
| **FIX-1** | Crash `AccessError` pada `res.partner` untuk internal user non-kampus (`_compute_academic_counts`, `_compute_admission_count`, `_compute_thesis_count`, dan `groups=` di view) | `69f5984` | `campus_core/models/res_partner.py:56-62`, `campus_core/views/res_partner_views.xml:12-51`, `campus_pmb/models/res_partner.py:19-23`, `campus_thesis/models/res_partner.py:16-20` |
| **FIX-2** | Dosen bisa input & simpan nilai KHS lewat form `academic.khs` (`perm_write=1`, `rule_lecturer_khs_write`, dan guard `AcademicKhs.write`) | `f29d274` | `campus_core/security/ir.model.access.csv:39`, `campus_core/security/campus_security.xml:248-257`, `campus_core/models/academic_khs.py:91-107` |
| **FIX-3** | Dosen & Staf Akademik tanpa `hr.group_hr_user` bisa membuka form/list/kanban `hr.employee` (`hr.version` ACL, `groups=` field chatter, compute `sudo()`) | `d90a50b` | `campus_employees/security/ir.model.access.csv:5-7`, `campus_employees/models/hr_employee.py:8-40, 524-533` |
| **FIX-4** | `ir.rule` cache (`clear_cache()`) dibersihkan di `HrEmployee.create`, `write`, dan `unlink` saat `user_id`/`active` berubah | `d90a50b` | `campus_employees/models/hr_employee.py:285-286, 321, 331-332` |
| **FIX-5** | Karyawan tanpa `academic_role` (`False`) kini ditolak oleh `_check_lecturer_eligible` | `4c7ee7f` | `campus_employees/models/academic_teaching.py:32` |
| **FIX-6** | Penugasan activity PMB (`_pmb_activity_assignee` via `_covers_program`) & penutupan bypass `write({'state': ...})` di `campus.admission` via `_STATE_TRANSITION_TOKEN` | `8fd1aa8` | `campus_employees/models/campus_jurisdiction.py:168-180`, `campus_pmb/models/admission.py:8, 317-354`, `campus_pmb/demo/campus_demo_admissions.xml:170-175` |

### B. Akun Demo Uji (Untuk Menjalankan Skenario di Bawah)
- **Admin :** `admin` (`hajril` / `wadoryou01`)
- **Admin Kampus:** `admin` / `admin` (atau `admincampus@gmail.com` / `123`)
- **Dosen (FTI - Teknik Informatika):** `dosen@kampus.test` / `demo123` (*Dr. Budi Hartono, M.Kom.*)
- **Staf Akademik / TU (FTI):** `staf@kampus.test` / `demo123` (*Dewi Lestari, S.E.*)
- **Staf PMB (FTI):** `pmb@kampus.test` / `demo123` (*Joko Santoso, S.Kom.*)
- **Mahasiswa Portal (Teknik Informatika):** `ahmad.fauzi@mahasiswa.test` / `demo123` (*Ahmad Fauzi*)

> **Tips Uji RPC di Browser:** Untuk skenario yang menguji celah ORM/RPC (yang tidak punya tombol langsung di form), tekan `F12` → tab **Console** saat sudah login di Odoo, lalu jalankan snippet `fetch('/web/dataset/call_kw', ...)` yang tersedia.

---

## 1. Bug Kritis & Tinggi yang BELUM Diperbaiki

### - [x] BUG-01: Reset KRS ke `draft` via `write({'state': 'draft'})` Melewati Guard Orphan KHS
- **Modul / Lokasi:** `campus_core/models/academic_krs.py:248-252` (`AcademicKrs.write`), `:537-573` (`action_set_draft`, `_check_no_orphan_khs`)
- **Masalah:** `action_set_draft()` dan `unlink()` memanggil `_check_no_orphan_khs()` untuk mencegah KRS direset jika KHS-nya masih ada. Namun `AcademicKrs.write()` hanya memeriksa `_STATE_TRANSITIONS` (yang mengizinkan `'approved' -> 'draft'`, `'revision' -> 'draft'`, `'rejected' -> 'draft'`) tanpa memanggil `_check_no_orphan_khs()`.
- **Skenario Test:**
  1. Login sebagai **Admin**, buka **Academic System → Studies → Student KRS**.
  2. Buka salah satu KRS berstatus **Locked** yang sudah punya **KHS** (catatan: catat ID KRS dari URL, misal `15`).
  3. Klik tombol **Unlock** sehingga status menjadi **Approved**.
  4. Buka **DevTools Console (`F12`)** dan jalankan:
     ```js
     fetch('/web/dataset/call_kw', {
       method: 'POST', headers: {'Content-Type': 'application/json'},
       body: JSON.stringify({jsonrpc: '2.0', method: 'call', params: {
         model: 'academic.krs', method: 'write', args: [[15], {state: 'draft'}], kwargs: {}
       }})
     }).then(r => r.json()).then(console.log);
     ```
  5. Refresh halaman KRS dan cek **Academic System → Studies → Academic Transcript (KHS)**.
- **Hasil Saat Ini (Bug):** `write()` berhasil mengembalikan KRS ke **Draft** sementara KHS lamanya tetap tertinggal (orphan KHS) dan masih dihitung dalam CGPA mahasiswa.
- **Hasil yang Diharapkan:** `write({'state': 'draft'})` wajib ditolak dengan `ValidationError` yang sama seperti tombol **Set to Draft** selama KHS terkait masih ada (atau proteksi token workflow seperti di `campus.admission`).

---

### - [x] BUG-02: `AcademicKhsLine.write` Menandai Nilai Kosong (`False`/`None`) Sebagai `is_graded=True` (`0.0` / `E`)
- **Modul / Lokasi:** `campus_core/models/academic_khs.py:231-247` (`AcademicKhsLine.write`) vs `:221-227` (`create`)
- **Masalah:** Di `create()`, baris hanya ditandai `is_graded=True` jika `vals['numeric_grade'] is not None`. Di `write()`, kode hanya mengecek `if 'numeric_grade' in vals:` (tanpa `is not None`), dan langsung memutasi dict `vals` milik caller (`vals.setdefault('is_graded', True)`).
- **Skenario Test:**
  1. Login sebagai **Admin**, buka **Academic System → Studies → Academic Transcript (KHS)**, buka salah satu KHS yang punya baris nilai belum dinilai (`Graded` = unchecked). Catat ID salah satu `academic.khs.line` (misal `42`).
  2. Di **DevTools Console (`F12`)**, jalankan:
     ```js
     fetch('/web/dataset/call_kw', {
       method: 'POST', headers: {'Content-Type': 'application/json'},
       body: JSON.stringify({jsonrpc: '2.0', method: 'call', params: {
         model: 'academic.khs.line', method: 'write', args: [[42], {numeric_grade: false}], kwargs: {}
       }})
     }).then(r => r.json()).then(console.log);
     ```
  3. Refresh form KHS tersebut.
- **Hasil Saat Ini (Bug):** Kolom **Graded** berubah menjadi aktif (`True`), `Letter Grade` berubah menjadi **`E`**, `Grade Points` menjadi **`0.00`**, dan IP semester langsung ikut turun.
- **Hasil yang Diharapkan:** Mengirim `numeric_grade: False/None` tidak menyalakan `is_graded=True`, dan `write()` bekerja pada salinan `vals = dict(vals)`.

---

### - [x] BUG-03 *(Bukan Bug — Sudah Terlindungi)*: `AcademicKhs.write` & `Command.LINK` Antar-KHS oleh Dosen
- **Modul / Lokasi:** `campus_core/models/academic_khs.py:104-106` (`AcademicKhs.write`), `:240-255` (`AcademicKhsLine.write`)
- **Status:** **Bukan bug runtime.** Saat Odoo mengeksekusi `Command.LINK` (`4`) pada `One2many` `line_ids` untuk baris dari KHS lain, Odoo memanggil `AcademicKhsLine.write({'khs_id': ...})` yang langsung diblokir dengan `AccessError` (*"Lecturers can only modify grade values, not transcript structure (khs_id)."*).

---

### - [x] BUG-04: Uninstall `campus_employees` Merusak `ir.rule` di `campus_core`
- **Modul / Lokasi:** `campus_employees/__init__.py:5-23`, `campus_employees/__manifest__.py`
- **Masalah:** `post_init_hook` mengubah `domain_force` pada `campus_core.rule_academic_staff_partner_write` dan `rule_academic_staff_partner_create` menjadi `"[('is_student', '=', True)] + user.employee_id._academic_jurisdiction_domain('program_id')"`, namun modul tidak mendefinisikan `uninstall_hook` untuk mengembalikannya ke `"[('is_student', '=', True)]"`.
- **Skenario Test:**
  1. *(Gunakan database uji salinan)* Login sebagai **Admin** → buka **Apps**.
  2. Cari **`campus_employees`** → klik menu titik tiga → **Uninstall**.
  3. Login sebagai **Staf Akademik** (`staf@kampus.test`), buka **Academic System → People → Students**, ubah salah satu data mahasiswa lalu klik **Save**.
- **Hasil Saat Ini (Bug):** Muncul `AttributeError: 'hr.employee' object has no attribute '_academic_jurisdiction_domain'`.
- **Hasil yang Diharapkan:** `uninstall_hook` memulihkan `domain_force` kedua rule tersebut ke `"[('is_student', '=', True)]"` sehingga `campus_core` tetap berjalan normal.

---

### - [x] BUG-05: `_create_account()` PMB Menghapus Nomor Telepon Mahasiswa Lama & Log `NIM: None`
- **Modul / Lokasi:** `campus_pmb/models/admission.py:601-613, 644` (`CampusAdmission._create_account`)
- **Masalah:** Jika `res.partner` (`is_student=True`) sudah ada dan belum punya `res.users`, `partner_vals` tetap menulis `'phone': record.phone` meski `record.phone` kosong (`False`). Baris log 644 juga mencetak `NIM: None` saat `partner.nim` sudah ada sebelumnya.
- **Skenario Test:**
  1. Login sebagai **Admin** → buat/siapkan student contact (`is_student=True`, `email='reapply@contoh.test'`, `phone='08111222333'`, sudah punya `nim`, tanpa `res.users`).
  2. Buka **Admissions → Applicants → New**, buat pendaftaran baru dengan `email='reapply@contoh.test'`, **kosongkan field Phone**.
  3. Lengkapi checklist dokumen, tandai pembayaran, lalu klik **Submit → Start Document Review → Accept → Register Student**.
  4. Buka profil mahasiswa tersebut di **Academic System → People → Students**.
- **Hasil Saat Ini (Bug):** Field **Phone** (`08111222333`) pada profil mahasiswa terhapus menjadi kosong, dan log server mencetak `student NIM: None`.
- **Hasil yang Diharapkan:** Field `phone` hanya di-update jika `record.phone` terisi, dan log mencetak NIM yang sebenarnya (`partner.nim or nim`).

---

### - [x] BUG-06: Race Condition Duplicate Email REST API (HTTP 500) & Bypass Lock Dokumen PMB
- **Modul / Lokasi:**
  - `campus_pmb/models/admission.py:719-738` (`_create_admission_from_portal`), `campus_pmb/controllers/main.py:173-187` (`api_admission_submit`)
  - `campus_pmb/models/admission.py:876-878` (`CampusAdmissionDocument.write`)
- **Masalah:**
  1. Dua submit API bersamaan dengan email yang sama sama-sama lolos `search_count` lalu membentur `UNIQUE (email, academic_year_id)`, melempar `IntegrityError` ke `except Exception:` sehingga API mengembalikan HTTP **500**.
  2. `CampusAdmissionDocument.write()` hanya mengecek status `line.admission_id.state` sebelum `super().write(vals)`, tanpa mengecek apabila `vals['admission_id']` memindahkan dokumen ke pendaftaran yang berstatus `accepted`/`registered`/`rejected`.
- **Skenario Test:**
  1. **API Race:** Di halaman publik, jalankan 2 `fetch('/api/admission/submit', ...)` paralel (`Promise.all`) lewat DevTools Console dengan payload valid dan email baru identik.
  2. **Document Lock Bypass:** Login sebagai **Staf PMB** (`pmb@kampus.test`). Catat ID dokumen dari admission berstatus **Draft** (misal doc ID `10`) dan ID admission berstatus **Registered** (misal admission ID `6`). Di DevTools Console jalankan `campus.admission.document.write([10], {admission_id: 6})`.
- **Hasil Saat Ini (Bug):** Salah satu request API menghasilkan HTTP `500` (*system error*); dokumen dari admission Draft berhasil dipindah ke admission Registered yang terkunci.
- **Hasil yang Diharapkan:** `IntegrityError` ditangani menjadi HTTP `400` dengan pesan ramah; `CampusAdmissionDocument.write()` menolak perubahan `admission_id` jika target admission berstatus `accepted`/`registered`/`rejected`.

---

### - [x] BUG-07: Bypass Workflow & Role Skripsi via `write({'state': ...})` (`campus_thesis`)
- **Modul / Lokasi:** `campus_thesis/models/campus_thesis.py:339-352, 424-485, 507-524` (`_check_protected_writes`, `write`)
- **Masalah:** `_check_protected_writes()` melarang penulisan langsung pada field `*_approved` dan `*_date`, **tetapi tidak menjaga field `'state'`**. Dosen atau Staf Akademik (yang memiliki `perm_write=1`) dapat memindahkan `state` langsung melalui `write()` sepanjang `_STATE_TRANSITIONS` tanpa melalui tombol/method aksi resmi.
- **Skenario Test:**
  1. Login sebagai **Dosen** (`dosen@kampus.test`) → buka **Academic System → Thesis & Graduation → Student Theses**.
  2. Buka skripsi mahasiswa bimbingannya dalam status **Draft** (atau **Supervisor Approval**). Catat ID-nya (misal `1`).
  3. Di **DevTools Console (`F12`)**, jalankan:
     ```js
     fetch('/web/dataset/call_kw', {
       method: 'POST', headers: {'Content-Type': 'application/json'},
       body: JSON.stringify({jsonrpc: '2.0', method: 'call', params: {
         model: 'campus.thesis', method: 'write', args: [[1], {state: 'cancelled'}], kwargs: {}
       }})
     }).then(r => r.json()).then(console.log);
     ```
     *(Atau saat status `supervisor_approval`, kirim `{state: 'proposal'}` tanpa persetujuan Co-Supervisor; atau saat `proposal`, kirim `{state: 'thesis'}` jika KRS Skripsi sudah ada tanpa mengisi `proposal_approved_date`.)*
- **Hasil Saat Ini (Bug):** Status berhasil berubah melewati hak akses `action_cancel`, tanpa flag persetujuan pembimbing, tanpa tanggal approval, dan tanpa menutup activity.
- **Hasil yang Diharapkan:** Terapkan token internal (seperti `_STATE_TRANSITION_TOKEN` pada `campus.admission`) agar perubahan `state` hanya sah melalui method workflow resmi.

---

### - [x] BUG-08: Mahasiswa Portal Bisa Mengaktifkan Kembali Skripsi yang Di-Cancel Staf
- **Modul / Lokasi:** `campus_thesis/controllers/portal.py:240-250` (`portal_my_thesis_reset_draft`), `campus_thesis/models/campus_thesis.py:688-702` (`action_reset_to_draft`)
- **Masalah:** `portal_my_thesis_reset_draft` berjalan dengan `sudo()` dan memanggil `action_reset_to_draft()`, yang mengizinkan baik `'supervisor_rejected'` maupun `'cancelled'` kembali ke `'draft'` tanpa pengecekan peran.
- **Skenario Test:**
  1. Login sebagai **Staf Akademik** (`staf@kampus.test`) → buka skripsi milik *Ahmad Fauzi* → klik tombol **Cancel** hingga status **Cancelled**.
  2. Login di Portal sebagai **Ahmad Fauzi** (`ahmad.fauzi@mahasiswa.test` / `demo123`) → buka `/my/thesis` → buka skripsi tersebut (catat ID, misal `1`).
  3. Ambil `csrf_token` (dari `/my/krs` atau elemen halaman), lalu di **DevTools Console** jalankan:
     ```js
     fetch('/my/thesis/1/reset_draft', {
       method: 'POST',
       headers: {'Content-Type': 'application/x-www-form-urlencoded'},
       body: new URLSearchParams({csrf_token: odoo.csrf_token})
     }).then(r => console.log(r.url));
     ```
  4. Refresh `/my/thesis/1`.
- **Hasil Saat Ini (Bug):** Skripsi berstatus **Cancelled** kembali menjadi **Draft** oleh mahasiswa (atau error `"A system error occurred."` karena bentrok unique index bila mahasiswa sudah punya skripsi aktif baru).
- **Hasil yang Diharapkan:** Portal hanya boleh me-reset status `'supervisor_rejected'`; status `'cancelled'` wajib ditolak (hanya Admin/Staf yang bisa me-reset skripsi cancelled dari backend).

---

### - [x] BUG-09: Re-upload Dokumen Yudisium Tidak Mereset `received=False` & Tabel Tidak Terkunci
- **Modul / Lokasi:**
  - `campus_thesis/controllers/portal.py:324-329` (`portal_my_thesis_upload_document`)
  - `campus_thesis/models/campus_thesis_document.py:88-98` (`CampusThesisDocument.write`), `campus_thesis/views/campus_thesis_views.xml:178-188`
- **Masalah:** Ketika mahasiswa mengunggah ulang file di `/my/thesis/<id>/upload_document/<doc_id>`, `received` tidak direset menjadi `False`. Selain itu, di backend tidak ada lock `readonly="state != 'yudisium_docs'"` pada `yudisium_document_ids`, sehingga staf masih bisa mencabut verifikasi setelah skripsi masuk ke tahap approval Yudisium atau Graduated.
- **Skenario Test:**
  1. Login sebagai **Admin/Dosen**, bawa skripsi mahasiswa hingga tahap **Yudisium Filing** (`yudisium_docs`).
  2. Login sebagai mahasiswa di `/my/thesis/<id>`, unggah semua dokumen wajib.
  3. Login sebagai **Staf Akademik** (`staf@kampus.test`), buka form skripsi → tab **Yudisium & Sequential Approvals** → centang **Verified / Received** pada semua baris wajib lalu simpan.
  4. Kembali ke browser **Mahasiswa**, refresh `/my/thesis/<id>`. Pada baris yang sudah berstatus **Verified**, unggah file baru lain lalu klik **Upload**.
- **Hasil Saat Ini (Bug):** File tertimpa berkas baru yang belum dicek staf, namun badge status tetap **Verified** dan tombol **Submit for Yudisium Sequential Approval** tetap aktif.
- **Hasil yang Diharapkan:** Re-upload oleh mahasiswa wajib menyetel `'received': False` (atau melarang upload ulang jika sudah diverifikasi), dan `yudisium_document_ids` terkunci di luar status `yudisium_docs`.

---

### - [x] BUG-10: Multi-Record Crash pada Wizard Penolakan & Skripsi untuk Mahasiswa Non-Aktif
- **Modul / Lokasi:**
  - `campus_thesis/models/campus_thesis.py:650-674, 851-872` (`_open_reject_wizard`, `action_supervisor_reject`, `action_yudisium_return_to_docs`)
  - `campus_thesis/models/campus_thesis.py:283-298, 300-324, 593-849` (`_validate_student_eligibility`, `_check_supervisors_valid`, workflow actions)
- **Masalah:**
  1. `_open_reject_wizard` memanggil `self.ensure_one()`. Jika `action_supervisor_reject` / `action_yudisium_return_to_docs` dipanggil untuk >1 record tanpa `reason`, langsung crash `ValueError`.
  2. `_validate_student_eligibility` tidak mengecek `student.student_status == 'active'`, dan tahap lanjutan sampai `action_yudisium_approve_dean()` tidak mengecek ulang apakah mahasiswa masih aktif (mahasiswa `Drop Out` / `On Leave` bisa dibuatkan skripsi hingga statusnya tertimpa menjadi `Graduated`).
  3. `_check_supervisors_valid` tidak memeriksa `supervisor_id.active` / `co_supervisor_id.active` ataupun keberadaan `user_id` pembimbing.
- **Skenario Test:**
  1. **Multi-record:** Buat 2 skripsi status `supervisor_approval`, centang keduanya di list view lalu panggil `action_supervisor_reject()` tanpa `reason` via Console/Server Action.
  2. **Non-active student:** Login sebagai **Admin**, ubah status *Nabila Putri* (yang sudah lulus Metopen) ke **On Leave** atau **Drop Out**. Buka **Thesis & Graduation → Student Theses → New**, pilih *Nabila Putri* lalu klik **Save**.
- **Hasil Saat Ini (Bug):** Skenario 1 crash `ValueError: Expected singleton`; Skenario 2 berhasil membuat draft skripsi untuk mahasiswa non-aktif.
- **Hasil yang Diharapkan:** Tambahkan `self.ensure_one()` di awal `action_supervisor_reject` & `action_yudisium_return_to_docs` bila membuka wizard; wajibkan `student.student_status == 'active'` saat pembuatan dan transisi kelulusan, serta pastikan pembimbing aktif dan memiliki user (saat submit).

---

## 2. Celah Keamanan (Security & Access Control) yang BELUM Diperbaiki

### - [x] SEC-01: Upload File Tanpa Validasi Tipe/MIME & Bug Path Windows di Portal Skripsi
- **Modul / Lokasi:** `campus_thesis/controllers/portal.py:92-102` (`_parse_uploaded_file`)
- **Masalah:** Tidak ada whitelist ekstensi/MIME (menerima `.html`, `.svg`, `.js`, `.exe`, `.sh`), dan `os.path.basename(upload.filename)` di server Linux tidak memotong backslash Windows (`C:\fakepath\file.pdf`).
- **Skenario Test:**
  1. Login sebagai mahasiswa di `/my/thesis/<id>` (tahap *Proposal*, *Thesis*, atau *Yudisium Filing*).
  2. Buat file lokal bernama `test.html` atau `xss.svg` berisi teks biasa.
  3. Pilih file tersebut di input **Draft File** atau **Upload File**, lalu klik **Submit Progress Log** / **Upload**.
- **Hasil Saat Ini (Bug):** File `.html`/`.svg` tersimpan ke database/attachment tanpa penolakan.
- **Hasil yang Diharapkan:** Hanya izinkan ekstensi/MIME aman (misal `.pdf`, `.doc`, `.docx`, `.jpg`, `.jpeg`, `.png`) dengan validasi magic header dasar dan sanitasi `ntpath.basename` + `os.path.basename`.

---

### - [x] SEC-02: Hak `unlink` Pendaftaran Terdaftar & CRUD Konfigurasi Global untuk Staf PMB
- **Modul / Lokasi:** `campus_pmb/security/ir.model.access.csv:3, 5, 10, 13`, `campus_pmb/models/admission.py` (tidak ada `unlink()`)
- **Masalah:** `group_pmb` memiliki `perm_unlink=1` pada `campus.admission` (termasuk record yang sudah `accepted`/`registered`, memutus jejak pembuatan NIM/user), dan memiliki hak ubah/hapus (`1,1,1,1`) pada konfigurasi global `campus.admission.fee` & `campus.admission.requirement` tanpa pembatasan.
- **Skenario Test:**
  1. Login sebagai **Staf PMB** (`pmb@kampus.test`, yurisdiksi FTI saja).
  2. Buka **Admissions → Configuration → Admission Fees** (atau **Document Requirements**), hapus satu aturan biaya global.
  3. Buka **Admissions → Applicants**, hapus filter *In Progress*, buka pendaftar berstatus **Registered** (*Salsabila Nur*), klik **⚙️ Actions → Delete**.
- **Hasil Saat Ini (Bug):** Staf PMB tingkat fakultas bisa menghapus aturan biaya kampus dan menghapus record admission yang sudah berstatus *Registered*.
- **Hasil yang Diharapkan:** Konfigurasi `fee`/`requirement` hanya boleh diubah/dihapus oleh `group_campus_administrator` (PMB Staff cukup read-only); `CampusAdmission.unlink()` harus memblokir penghapusan status `accepted`/`registered`.

---

### - [x] SEC-03: Email Enumeration & Tanpa Batas Panjang Input di REST API PMB
- **Modul / Lokasi:** `campus_pmb/controllers/main.py:119-178`, `campus_pmb/models/admission.py:700-727`
- **Masalah:** `POST /api/admission/submit` membocorkan eksistensi email pendaftar lain (*"An application with this email address already exists..."*) dan tidak membatasi panjang string (`name`, `email`, `previous_school`).
- **Skenario Test:**
  1. Di halaman publik (tanpa login), buka DevTools Console dan kirim `POST /api/admission/submit` memakai `email: 'putri.anggraini@calon.test'` dan `name: 'A'.repeat(5000)`.
- **Hasil Saat Ini (Bug):** API langsung mengonfirmasi bahwa email tersebut sudah mendaftar tahun ini (HTTP 400); input string sangat panjang diteruskan ke ORM tanpa batas.
- **Hasil yang Diharapkan:** Terapkan batas panjang field yang wajar dan pertimbangkan rate-limiting / respons yang tidak mengekspos status pelamar secara publik sesuai kebutuhan bisnis.

---

### - [x] SEC-04: Panel Demo Login Permanen, Bahasa Campuran, & `target="_blank"` Tanpa `rel="noopener noreferrer"`
- **Modul / Lokasi:**
  - `campus_website/views/website_login_templates.xml:4-62`
  - `campus_website/views/website_layout_core.xml:75, 80`
  - `campus_website/static/src/js/campus_website.js:19`
- **Masalah:** Link eksternal (`wa.me`, `linkedin.com`) memakai `target="_blank"` tanpa `rel="noopener noreferrer"`; halaman `/web/login` selalu merender panel kredensial admin (`admincampus@gmail.com` / `123`) bahkan di non-demo DB, serta baris 58 memakai teks hardcode bahasa Indonesia `"Login Admin Kampus"`.
- **Skenario Test:**
  1. Buka `/web/login` dalam mode desktop & mobile (ubah lebar layar DevTools < 992px).
  2. Inspeksi elemen (`F12` → Elements) pada tautan WhatsApp di header dan footer.
- **Hasil Saat Ini (Bug):** Di tampilan mobile tertulis `"Login Admin Kampus"` (tidak ikut terjemahan Inggris), dan link `target="_blank"` tidak memiliki `rel="noopener noreferrer"`.
- **Hasil yang Diharapkan:** Tambahkan `rel="noopener noreferrer"` pada semua `target="_blank"`, ganti teks tombol ke bahasa Inggris (terjemahkan via `id.po`), dan pertimbangkan men-gate panel demo via system parameter/demo flag.

---

### - [x] SEC-05: Transfer Yurisdiksi KRS/KHS via `write()` & Perubahan `academic_role` Pegawai Tanpa `user_id`
- **Modul / Lokasi:**
  - `campus_employees/models/res_partner.py:70-76` vs model `academic.krs`, `academic.khs`, `academic.krs.line`, `academic.khs.line`
  - `campus_employees/models/hr_employee.py:480-518` (`_sync_academic_user_role`)
- **Masalah:** Re-check `self.check_access('write')` pasca-`write` baru diterapkan di `res.partner`, belum di KRS/KHS/lines. Di `hr.employee`, `_check_may_grant_academic_groups()` tidak terpanggil bila pegawai belum memiliki `user_id` (`if not users: return`).
- **Skenario Test:**
  1. Login sebagai **Staf Akademik** (`staf@kampus.test`, yurisdiksi FTI). Buka satu KRS FTI, lalu via Console panggil `write` mengganti `student_id` ke mahasiswa **FEB** (*Manajemen*) dan `program_id` ke FEB.
  2. Login sebagai **HR Officer** (`hr.group_hr_user` tanpa Admin Kampus), buka **Employees**, pilih pegawai tanpa `user_id`, ubah `academic_role` ke `Academic Staff (TU)`, klik Save.
- **Hasil Saat Ini (Bug):** Kedua perubahan berhasil tanpa `AccessError`.
- **Hasil yang Diharapkan:** Transfer KRS/KHS keluar yurisdiksi harus gagal `check_access('write')`; perubahan `academic_role` pada `hr.employee` harus selalu memanggil `_check_may_grant_academic_groups()`.

---

## 3. Bug Menengah & Edge Cases yang BELUM Diperbaiki

### `campus_core`
- [x] **MED-01: `faculty_id` & `program_id` di `AcademicKrs` tidak masuk `protected_fields`** (`academic_krs.py:106-107, 190-195`).
  - *Uji:* Buka KRS status `submitted`/`locked`, jalankan `academic.krs.write([id], {program_id: <other_id>})` via Console sebagai Dosen PA/Staf. *Saat ini:* Berhasil mengubah snapshot historis KRS. *Harapan:* Masuk `protected_fields` agar terkunci di luar `draft`/`revision`.
- [x] **MED-02: Child line bisa dibuat yatim / tanpa induk (`krs_id`, `subject_id`, `class_id` belum `required=True`)** (`academic_krs.py:596, 603`, `academic_class_schedule.py:18`).
  - *Uji:* Via Console/Import, buat `academic.krs.line` dengan `{krs_id: <id>, schedule_id: <sched_id>, subject_id: false}` lalu submit dan klik **Lock & Generate KHS**; atau buat `academic.class.schedule` dengan `class_id: false` di jam bentrok. *Saat ini:* KRS crash saat Lock; jadwal tanpa kelas lolos cek bentrok. *Harapan:* Wajibkan `krs_id`, `subject_id` (atau hitung ulang jika `schedule_id` ada), dan `class_id` (`required=True`).
- [x] **MED-03: Ketidaksinkronan tombol UI vs server action & grup pada KRS/Class/Package** (`academic_krs_views.xml:161`, `academic_krs.py:212`, `academic_class_views.xml:61, 74`, `academic_course_package_views.xml:25`).
  - *Uji:* (a) Centang KRS berstatus **Needs Revision** → klik **Actions → Mass Submit**; (b) Login sebagai **Dosen** (`dosen@kampus.test`) → buka **Classes** / **Course Packages**, klik tombol **Assign Schedule (Massive)** / **Generate Sessions** / **Generate KRS**. *Saat ini:* Mass Submit melewatkan `revision`; Dosen melihat tombol dan terkena `AccessError` saat klik; Dosen PA juga bisa memanggil transisi `('revision', 'draft')` lewat RPC walau tombol *Set to Draft* khusus Admin. *Harapan:* Mass Submit ikut memproses `revision`; tombol class/package diberi `groups=`; `_ADMIN_STATE_TRANSITIONS` mencakup `('revision', 'draft')` & `('rejected', 'draft')`.
- [x] **MED-04: `KrsGeneratorWizard` tidak memvalidasi kesamaan prodi di server** (`krs_generator_wizard.py:43-85`).
  - *Uji:* Buka Course Package Prodi IF → buka wizard Generate KRS → sisipkan ID mahasiswa prodi MN lewat Console lalu klik **Generate KRS**. *Saat ini:* KRS dibuat untuk mahasiswa MN dengan stempel prodi IF. *Harapan:* Tolak dengan `ValidationError` jika ada mahasiswa berbeda `program_id`.
- [x] **MED-05: Stale `@api.depends` pada `AcademicCoursePackage.total_credits` & `AcademicClass.name`** (`academic_krs.py:36`, `academic_class.py:25`).
  - *Uji:* Buka **Subjects**, ubah SKS atau Nama mata kuliah yang sudah dipakai di **Course Package** & **Class**, lalu cek kedua record tersebut. *Saat ini:* `Total Credits` paket & `Class Name` tidak ikut berubah. *Harapan:* Depend ke `line_ids.subject_id.credits` dan `('subject_id.name', 'academic_year_id.name')`.
- [x] **MED-06: Band batas SKS `0.00` = `24` SKS tidak monoton** (`academic_credit_limit_data.xml:8-30`).
  - *Uji:* Isi nilai KHS mahasiswa sehingga IPK = `1.50` (misal nilai `D` / `45`), lalu ajukan KRS `22` SKS. Bandingkan dengan mahasiswa IPK `2.20` yang mengajukan `19` SKS. *Saat ini:* IPK `1.50` lolos 22 SKS (band `0.00` -> `24`), sedangkan IPK `2.20` ditolak (band `2.00` -> `18`). *Harapan:* Bedakan mahasiswa baru (`graded_credits == 0`) dari mahasiswa dengan IPK rendah (`0.00 < IPK < 2.00`).
- [x] **MED-07: `AcademicProgram.write()` tidak membersihkan `parent_id` Kaprodi lama & normalisasi `code`** (`academic_institution.py:95-97, 200-201, 266-271`).
  - *Uji:* Buka **Configuration → Programs**, ganti **Head of Program** dari Dosen A ke Dosen B, lalu cek field **Manager** pada profil HR Dosen A. *Saat ini:* Manager Dosen A masih menunjuk ke Dekan. *Harapan:* Bersihkan `parent_id` Kaprodi lama seperti di `AcademicFaculty.write()`, dan normalisasi `code` dengan `.strip().upper()`.
- [x] **MED-08: Perubahan `AcademicClass.academic_year_id`, lock order, `GradeScale` desimal, `raise_if_not_found`, & falsy `name`** (`academic_class_schedule.py:128-131, 170`, `academic_grade_scale.py:63`, `academic_krs.py:151, 475`, `academic_khs.py:87`).
  - *Uji:* Ubah **Academic Year** pada form **Classes** yang sudah punya jadwal hingga bentrok dengan kelas lain di tahun baru tersebut; atau kirim `name: false` saat `create` KRS/KHS/Admission/Thesis via Console. *Saat ini:* Overlap tahun baru tidak dicek ulang; `name: false` memicu error SQL `NOT NULL`. *Harapan:* Re-validasi overlap saat `academic_year_id` berubah, gunakan `tuple(sorted(self.ids))`, dan cek `if not vals.get('name') or vals.get('name') == 'New':`.

### `campus_employees`
- [x] **MED-09: Self-loop manajer pada `_onchange_department_id_sync_manager`** (`hr_employee.py:245-255`).
  - *Uji:* Buka profil karyawan yang menjabat sebagai **Dekan**, lalu pilih **Department** milik salah satu prodi di fakultasnya di mana ia juga manajer departemen tersebut. *Saat ini:* Field `Manager` (`parent_id`) terisi dirinya sendiri. *Harapan:* Cek `parent_manager != self._origin`.
- [x] **MED-10: Mahasiswa arsip diabaikan move guard & dosen PA tanpa prodi cocok dengan mahasiswa tanpa prodi** (`hr_employee.py:399`, `campus_employees/models/res_partner.py:58`).
  - *Uji:* (a) Arsipkan mahasiswa yang masih punya PA, lalu pindahkan prodi PA tersebut; (b) Set `program_id=False` pada dosen dan mahasiswa, lalu pasang sebagai PA via Console/Import. *Saat ini:* Keduanya lolos. *Harapan:* Gunakan `active_test=False` di move guard PA, dan tolak PA jika `not student.program_id or not advisor.program_id`.
- [x] **MED-11: Command pengosongan `program_ids` di `CampusJurisdiction.create`/`write`** (`campus_jurisdiction.py:126, 133`).
  - *Uji:* Kirim `create`/`write` `{all_faculties: true, program_ids: [[6, 0, []]]}` tanpa `all_programs`. *Saat ini:* `all_programs` tidak otomatis diset `True`, lalu `_domain_for` mengembalikan `[(0, '=', 1)]` (buta total). *Harapan:* Evaluasi isi efektif `program_ids`, bukan sekadar truthiness list command.

### `campus_pmb`
- [x] **MED-12: Field `name`, `phone`, `previous_school`, `registration_date` tidak terkunci setelah `registered`/`rejected`** (`admission_views.xml:34, 40, 41, 44`, `admission.py:292-298`).
  - *Uji:* Buka admission berstatus **Registered** (*Salsabila Nur*), edit `Applicant Name` atau `Phone`, lalu klik Save. *Saat ini:* Masih bisa diubah setelah final. *Harapan:* Kunci di model & form setelah `registered`/`rejected`.

### `campus_portal` & `campus_thesis`
- [x] **MED-13: Portal KRS `add_line`/`delete_line` tidak cek periode KRS & breadcrumb detail KRS hilang** (`campus_portal/controllers/portal.py:288-370`, `campus_portal/views/portal_templates.xml:169-175`).
  - *Uji:* Tutup tanggal periode KRS di **Academic Years**, lalu login sebagai *Ahmad Fauzi* → buka `/my/krs/<id>` yang sudah berstatus Draft. *Saat ini:* Tidak ada breadcrumb di atas halaman; tombol **Take** & **Remove** masih berhasil mengubah isi KRS walau periode KRS tutup. *Harapan:* Tampilkan breadcrumb `My KRS / <No KRS>` dan blokir mutasi KRS di luar periode KRS.
- [x] **MED-14: Dropdown pembimbing portal memakai `partner.program_id` bukan `thesis.program_id`** (`campus_thesis/controllers/portal.py:173`).
  - *Uji:* Setelah mahasiswa membuat draft skripsi, Admin memindahkan `program_id` pada profil mahasiswa, lalu mahasiswa membuka `/my/thesis/<id>` dan memilih pembimbing dari dropdown. *Saat ini:* Dropdown menampilkan dosen prodi baru, lalu gagal saat Save. *Harapan:* Filter dosen pembimbing utama berdasarkan `thesis.program_id`.
- [x] **MED-15: Wizard penolakan menerima spasi kosong & aktivitas tidak sinkron saat ganti pembimbing** (`thesis_reject_wizard.py:19-25`, `campus_thesis.py:511-524`).
  - *Uji:* (a) Klik **Reject** → isi `   ` (spasi) → konfirmasi; (b) Admin mengganti `supervisor_id` atau mengosongkan `co_supervisor_id` saat status `supervisor_approval`. *Saat ini:* Spasi tersimpan; activity pembimbing lama tertinggal / status tidak lanjut walau `supervisor_approved` sudah `True`. *Harapan:* `.strip()` reason wajib tidak kosong; kelola activity dan evaluasi ulang transisi saat pembimbing diganti.
- [x] **MED-16: `action_assign_nearest_graduation` menimpa jadwal lama tanpa chatter & log bimbingan bisa di-approve saat skripsi `cancelled`/`graduated`** (`campus_thesis.py:890-901`, `campus_thesis_progress.py:94-110`).
  - *Uji:* (a) Panggil `action_assign_nearest_graduation` pada skripsi yang sudah punya `graduation_id`; (b) Buka skripsi status **Cancelled**, klik **Approve** / **Revise** pada tab *Guidance & Progress Logs*. *Saat ini:* Jadwal tertimpa tanpa chatter; progres skripsi yang sudah batal masih bisa diubah. *Harapan:* Lindungi `graduation_id` yang sudah ada (atau catat chatter bila diganti) dan kunci review progress log jika skripsi `graduated`/`cancelled`.
- [x] **MED-17: Tombol header & halaman dokumen `campus_thesis` tidak dibatasi `groups=` / `readonly`** (`campus_thesis/views/campus_thesis_views.xml:12-30, 111`).
  - *Uji:* Login sebagai **Staf Akademik** (`staf@kampus.test`), buka form skripsi berstatus `supervisor_approval` / `yudisium_supervisor`, klik tombol **Approve Supervision** atau **Approve Yudisium**. *Saat ini:* Tombol terlihat dan error `AccessError` saat diklik. *Harapan:* Tambahkan `groups=` sesuai aktor masing-masing dan `readonly` pada `progress_line_ids` di luar stage `proposal`/`thesis`.

---

## 4. Clean Code, Performa (N+1), Dead Code & Duplikasi

- [x] **CLEAN-01: Bersihkan 3 file `.pyc` yatim (sumbernya sudah tidak ada)**
  - `campus_employees/models/__pycache__/academic_class_schedule.cpython-314.pyc`
  - `campus_pmb/controllers/__pycache__/api.cpython-314.pyc`
  - `campus_pmb/tests/__pycache__/test_admission_api.cpython-314.pyc`
- [x] **CLEAN-02: Hilangkan N+1 Query & Pagination Memori Penuh**
  - `campus_core/models/academic_krs.py:352-375` (`_check_section_quota` memanggil `_enrolled_count` per baris alih-alih batch `_enrolled_counts()`), `:489-517` (`action_lock`), `:559-573` (`_check_no_orphan_khs`), `academic_khs.py:113-124` (`_check_requires_approved_krs`).
  - `campus_employees/models/hr_employee.py:369-426` (`_what_still_points_here` melakukan 5 query per employee).
  - `campus_pmb/models/admission.py:194-206, 388-413, 536-644` (`create`, `action_submit`, `action_start_document_review`, `_create_account`).
  - `campus_portal/controllers/portal.py:162-173, 398-409` (`portal_my_krs` & `portal_my_khs` memuat seluruh record lalu slicing Python, bukan SQL `limit`/`offset` + `search_count`).
  - `campus_core/models/res_partner.py:56-62` & `campus_thesis/models/res_partner.py:16-20` (hitung count memakai `_read_group`).
- [x] **CLEAN-03: Hapus Dead Code & Komentar Rusak**
  - `_SYNC` di `campus_core/models/academic_institution.py:7`
  - `_get_grade_from_score` di `campus_core/models/academic_khs.py:196-202`
  - `pmb_skip_lock`, walrus `_REGISTERED_LOCKED_FIELDS`, dan `_default_document_types` di `campus_pmb/models/admission.py:302, 304, 826-835`
  - `nearest_graduation`, `'lecturers'`, dan `post.get('note')` di `campus_thesis/controllers/portal.py:131, 176-191, 328`
  - Cabang unreachable di `campus_thesis/models/campus_thesis_progress.py:69-72`
  - Komentar terpotong di `campus_core/models/academic_krs.py:604-608`
- [x] **CLEAN-04: Kurangi Duplikasi (DRY) & Coupling Antar-Modul**
  - Satukan `report_errors_to` / `_redirect_with_error` (`campus_portal` & `campus_thesis`).
  - Satukan helper pengecekan bentrok jadwal (`academic_krs.py`, `assign_schedule_wizard.py`, `campus_portal/controllers/portal.py`).
  - Satukan duplikasi di `campus_pmb/models/admission.py` (`currency_id`, blok activity di `action_submit` & `action_start_document_review`, cek `unpaid_reg`).
  - Hilangkan hardcode `'pmb'` dari `campus_employees/views/hr_employee_views.xml:88`.
  - Ganti `[(4, lang.id)]` dengan `Command.link(lang.id)` di `campus_website/__init__.py:32`.
  - Hapus salah satu menu duplikat *Graduation Schedules* di `campus_thesis/views/menus.xml:15-37`.

---

## 5. QWeb Report, Dokumentasi, `i18n`, dan Test Suite

- [x] **DOC-01: Perbaikan Layout QWeb Report KHS & Format Tanggal Report Thesis**
  - **Lokasi:** `campus_core/report/report_khs_template.xml:23-24, 85-97`, `campus_thesis/report/report_thesis_template.xml:60, 64, 94, 106, 118`
  - *Uji:* Cetak **Print KHS** (cek pergeseran sel `<tfoot>` terhadap header 7 kolom) dan **Print Thesis Clearance** pada skripsi *Graduated* (cek timestamp UTC mentah).
  - *Harapan:* Sel `<tfoot>` KHS sejajar dengan kolom tabel dan header KHS memakai snapshot prodi term terkait; tanggal report Thesis diformat dengan `t-field` / `format_datetime`.

- [x] **DOC-02: Sinkronisasi Dokumentasi Website Homepage (`/`) & `README.md`**
  - **Lokasi:** `campus_employees/views/website_homepage_employees.xml:63, 79, 94-95`, `campus_pmb/views/website_homepage_pmb.xml:63, 68, 110`, `campus_thesis/views/website_homepage_thesis.xml:48, 53-54, 108`, `campus_core/README.md:162-163`
  - *Uji:* Buka `/` dan periksa tab *HR & Staff*, *PMB*, dan *Thesis*.
  - *Harapan:* Hapus penyebutan role `"Dean"` di Job Position, ubah `"PMB / Academic Jurisdiction"` → `"Jurisdiction"`, perbaiki contoh `PMB/2026/00001` (5 digit) & alur `Draft → Submitted`, serta jelaskan bahwa Co-Supervisor (jika ada) wajib ikut menyetujui dan berhak menolak.

- [x] **DOC-03: Pembersihan String Source & Sinkronisasi `.pot` / `id.po`**
  - **Lokasi:** `campus_core/models/academic_class.py:114` (`Session {i+1}: ...` belum pakai `_()`), `campus_pmb/models/admission.py:765, 915` (`'All Paths'` belum pakai `_()`), `campus_employees/models/academic_teaching.py:33, 45` (`records.env._(...)`), serta file `i18n/*.pot` dan `i18n/id.po` di `campus_core`, `campus_employees`, `campus_pmb`, `campus_thesis`.
  - *Uji:* Ganti bahasa user ke **Indonesian (`id_ID`)**, jalankan *Generate Sessions* atau buka dropdown *Admission Path* di *Admission Fees*.
  - *Harapan:* Semua string UI/error terbungkus `_()` yang terekstrak ke `.pot`, seluruh `.pot` dan `id.po` di-regenerate agar bersih dari entry usang.

- [x] **TEST-01: Perbaikan Bug di Test Suite & Penambahan Test Regresi**
  - **Temuan baru (`ec6ebf4`):** `campus_pmb/tests/test_ui_tours.py:56-59` memakai fallback `'document_type': 'ijazah'` yang bukan key valid (seharusnya `'diploma'`).
    - *Uji:* Hapus seluruh record `campus.admission.requirement` pada DB kosong lalu jalankan `TestCampusPmbUiTours`. *Bug:* `ValueError: Wrong value for ... document_type: 'ijazah'`.
  - **Standalone `campus_employees`:** `campus_employees/tests/test_jurisdiction.py:131-136` meng-assert `'pmb'` ada di `campus.jurisdiction.scope`, padahal `campus_employees` tidak bergantung pada `campus_pmb`.
    - *Uji:* Jalankan test `campus_employees` di database yang hanya menginstal `campus_employees` tanpa `campus_pmb`. *Bug:* Test gagal.
  - **Test lemah / belum ada regresi:** Perkuat `test_reusing_a_student_does_not_burn_a_sequence_number` & `test_applying_twice_is_reported_to_the_applicant`, serta tambahkan test regresi untuk seluruh poin `BUG-01` s.d. `BUG-10` dan `SEC-01` s.d. `SEC-05`.
