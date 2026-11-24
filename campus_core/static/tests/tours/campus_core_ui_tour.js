import { registry } from "@web/core/registry";

function listThenFormSteps(label) {
    return [
        {
            content: `${label}: wait for list view`,
            trigger: ".o_list_view .o_data_row td.o_data_cell",
            run: "click",
        },
        {
            content: `${label}: verify form view rendered`,
            trigger: ".o_form_view .o_form_sheet",
        },
    ];
}

registry.category("web_tour.tours").add("campus_core_accountant_contact_ui_tour", {
    steps: () => [
        {
            content: "Verify contact form renders without Access Error for plain internal user",
            trigger: ".o_form_view .o_form_sheet",
            run: () => {
                if (document.querySelector('button[name="action_open_krs"], button[name="action_open_khs"]')) {
                    throw new Error("Academic stat buttons should be hidden for plain internal users.");
                }
            },
        },
    ],
});

registry.category("web_tour.tours").add("campus_core_lecturer_khs_grading_ui_tour", {
    steps: () => [
        {
            content: "Verify KHS form opens in editable mode and click Numeric Grade cell",
            trigger: '.o_form_view .o_field_one2many td[name="numeric_grade"]',
            run: "click",
        },
        {
            content: "Enter grade 85",
            trigger: '.o_form_view .o_field_one2many td[name="numeric_grade"] input',
            run: "edit 85",
        },
        {
            content: "Save KHS form",
            trigger: ".o_form_button_save",
            run: "click",
        },
        {
            content: "Wait for computed Letter Grade A after save",
            trigger: '.o_form_view .o_field_one2many td[name="letter_grade"]:contains("A")',
        },
    ],
});

registry.category("web_tour.tours").add("campus_core_list_to_form_ui_tour", {
    steps: () => listThenFormSteps("Master/Academic view"),
});

registry.category("web_tour.tours").add("campus_core_list_only_ui_tour", {
    steps: () => [
        {
            content: "Verify inline-editable list view renders rows cleanly",
            trigger: ".o_list_view .o_data_row",
        },
    ],
});

registry.category("web_tour.tours").add("campus_core_calendar_to_list_form_ui_tour", {
    steps: () => [
        {
            content: "Verify calendar view renders cleanly",
            trigger: ".o_calendar_view",
        },
        {
            content: "Switch from calendar to list view",
            trigger: "button.o_switch_view.o_list",
            run: "click",
        },
        {
            content: "Open session row from list view",
            trigger: ".o_list_view .o_data_row td.o_data_cell",
            run: "click",
        },
        {
            content: "Verify session form view rendered",
            trigger: ".o_form_view .o_form_sheet",
        },
    ],
});

registry.category("web_tour.tours").add("campus_core_krs_workflow_ui_tour", {
    steps: () => [
        {
            content: "Submit Draft KRS",
            trigger: '.o_form_view button[name="action_submit"]',
            run: "click",
        },
        {
            content: "Approve Submitted KRS",
            trigger: '.o_form_view button[name="action_approve"]',
            run: "click",
        },
        {
            content: "Lock Approved KRS & Generate KHS",
            trigger: '.o_form_view button[name="action_lock"]',
            run: "click",
        },
        {
            content: "Unlock Locked KRS",
            trigger: '.o_form_view button[name="action_unlock"]',
            run: "click",
        },
        {
            content: "Re-Lock KRS",
            trigger: '.o_form_view button[name="action_lock"]',
            run: "click",
        },
        {
            content: "Verify Unlock button & Chatter rendered",
            trigger: '.o_form_view button[name="action_unlock"]',
        },
    ],
});

registry.category("web_tour.tours").add("campus_core_student_stat_buttons_ui_tour", {
    steps: () => [
        {
            content: "Open first student row from Students list",
            trigger: ".o_list_view .o_data_row td.o_data_cell",
            run: "click",
        },
        {
            content: "Verify KHS stat button is visible on student form",
            trigger: '.o_form_view button[name="action_open_khs"]',
        },
        {
            content: "Click KRS stat button on student form",
            trigger: '.o_form_view button[name="action_open_krs"]',
            run: "click",
        },
        {
            content: "Verify KRS view opened from student stat button",
            trigger: ".o_list_view, .o_form_view",
        },
    ],
});

registry.category("web_tour.tours").add("campus_core_create_faculty_ui_tour", {
    steps: () => [
        {
            content: "Click New button on Faculties list",
            trigger: ".o_list_button_add",
            run: "click",
        },
        {
            content: "Enter Faculty Name",
            trigger: '.o_form_view div[name="name"] input',
            run: "edit ZZTEST Fakultas UI",
        },
        {
            content: "Enter Faculty Code",
            trigger: '.o_form_view div[name="code"] input',
            run: "edit ZZUIFAC",
        },
        {
            content: "Save new Faculty",
            trigger: ".o_form_button_save",
            run: "click",
        },
        {
            content: "Wait for save to complete (Save button hidden)",
            trigger: ".o_form_view .o_form_button_save:not(:visible)",
        },
    ],
});
