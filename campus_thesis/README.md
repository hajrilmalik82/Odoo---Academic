# Campus Thesis & Graduation (`campus_thesis`)

End-to-end student thesis (Skripsi), Yudisium clearance, and Graduation (Wisuda) management for the Campus Academic SIAKAD suite on Odoo 19.

## Key Capabilities

1. **Curriculum Eligibility Gates (`academic.subject` & `res.partner`)**
   - Subjects carry a `thesis_role` classification (`Regular`, `Research Methodology`, `Thesis / Final Project`).
   - Only active students who have **passed** a Research Methodology subject in KHS can register or submit a thesis.
   - Proceeding from an approved proposal into the Thesis Stage is gated on enrolling in a Thesis subject in an **Approved or Locked KRS**.

2. **Supervisor Selection & Lecturer Review**
   - Students select a Primary Supervisor (required) and optional Co-Supervisor from active lecturers.
   - Assigned supervisors approve or reject (with reason) directly from the backend.

3. **Proposal & Thesis Guidance Progress Logs (`campus.thesis.progress`)**
   - Students submit chapter/milestone progress notes and attachments via the Student Portal (`/my/thesis/<id>`).
   - Assigned supervisors review and approve/request revisions, driving the stage progress bars.

4. **Yudisium Filing & Sequential 3-Step Approval**
   - Configurable Yudisium document requirements (`campus.thesis.requirement`) auto-populate per-thesis document checklists (`campus.thesis.document`).
   - Students upload files via the Portal; Academic Staff verify documents.
   - Strict sequential clearance enforced both in workflow buttons and ORM constraints:
     1. **Primary Thesis Supervisor**
     2. **Academic Advisor (PA)**
     3. **Dean of Faculty**

5. **Nearest Graduation (Wisuda) Assignment**
   - Final Dean approval transitions the student's `student_status` to `graduated` and automatically assigns the nearest upcoming open graduation schedule (`campus.graduation.schedule`) within registration deadlines and quota.

6. **Student Portal & PDF Clearance Sheet**
   - Full portal workspace at `/my/thesis` and `/my/thesis/<id>` with horizontal ownership isolation, CSRF protection, and downloadable PDF clearance sheet (`/my/thesis/<id>/report`).
