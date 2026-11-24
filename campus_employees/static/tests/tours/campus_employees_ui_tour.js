import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("campus_employees_lecturer_views_ui_tour", {
    steps: () => [
        {
            content: "Open lecturer row from Lecturers list",
            trigger: '.o_list_view td.o_data_cell:contains("ZZTEST Dosen PA")',
            run: "click",
        },
        {
            content: "Verify employee form and Lecturer Profile tab load without Access Error",
            trigger: '.o_form_view a.nav-link:contains("Lecturer Profile")',
            run: "click",
        },
        {
            content: "Verify Chatter renders cleanly",
            trigger: ".o_form_view .o-mail-Chatter",
        },
    ],
});

registry.category("web_tour.tours").add("campus_employees_kanban_ui_tour", {
    steps: () => [
        {
            content: "Verify Academic Staff kanban view loads without Access Error",
            trigger: ".o_kanban_renderer",
        },
    ],
});

registry.category("web_tour.tours").add("campus_employees_admin_kanban_switch_ui_tour", {
    steps: () => [
        {
            content: "Open first lecturer row from list view",
            trigger: ".o_list_view .o_data_row td.o_data_cell",
            run: "click",
        },
        {
            content: "Verify Lecturer form sheet and Lecturer Profile tab",
            trigger: '.o_form_view a.nav-link:contains("Lecturer Profile")',
        },
    ],
});

registry.category("web_tour.tours").add("campus_employees_kanban_to_form_ui_tour", {
    steps: () => [
        {
            content: "Click first kanban card",
            trigger: ".o_kanban_renderer .o_kanban_record",
            run: "click",
        },
        {
            content: "Verify form view rendered",
            trigger: ".o_form_view .o_form_sheet",
        },
    ],
});

registry.category("web_tour.tours").add("campus_employees_homepage_tab_ui_tour", {
    url: "/",
    steps: () => [
        {
            content: "Click Campus Employees portfolio tab on homepage",
            trigger: "#tab-employee",
            run: "click",
        },
        {
            content: "Verify Campus Employees tab pane becomes active",
            trigger: "#content-employee.active",
        },
    ],
});
