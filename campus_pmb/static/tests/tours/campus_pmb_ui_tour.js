import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("campus_pmb_applicant_submit_ui_tour", {
    steps: () => [
        {
            content: "Click Submit button on Draft admission form",
            trigger: '.o_form_view button[name="action_submit"]',
            run: "click",
        },
        {
            content: "Verify admission transitioned to Submitted (Start Document Review button appears)",
            trigger: '.o_form_view button[name="action_start_document_review"]',
        },
        {
            content: "Verify Chatter renders planned activities cleanly",
            trigger: ".o_form_view .o-mail-Chatter",
        },
    ],
});

registry.category("web_tour.tours").add("campus_pmb_accept_and_register_ui_tour", {
    steps: () => [
        {
            content: "Click Accept button on Document Review admission form",
            trigger: '.o_form_view button[name="action_accept"]',
            run: "click",
        },
        {
            content: "Click Register Student button on Accepted admission form",
            trigger: '.o_form_view button[name="action_register"]',
            run: "click",
        },
        {
            content: "Verify admission transitioned to Registered in statusbar",
            trigger: '.o_form_view .o_statusbar_status button[data-value="registered"][aria-checked="true"], .o_form_view .o_statusbar_status button[data-value="registered"].o_arrow_button_current',
        },
    ],
});

registry.category("web_tour.tours").add("campus_pmb_list_only_ui_tour", {
    steps: () => [
        {
            content: "Verify inline-editable PMB list view renders rows cleanly",
            trigger: ".o_list_view .o_data_row",
        },
    ],
});

registry.category("web_tour.tours").add("campus_pmb_list_or_kanban_to_form_ui_tour", {
    steps: () => [
        {
            content: "Open first record from list or kanban view",
            trigger: ".o_list_view .o_data_row td.o_data_cell, .o_kanban_renderer .o_kanban_record",
            run: "click",
        },
        {
            content: "Verify form sheet rendered cleanly",
            trigger: ".o_form_view .o_form_sheet",
        },
    ],
});

registry.category("web_tour.tours").add("campus_pmb_homepage_tab_ui_tour", {
    url: "/",
    steps: () => [
        {
            content: "Click PMB portfolio tab on homepage",
            trigger: "#tab-pmb",
            run: "click",
        },
        {
            content: "Verify PMB tab pane becomes active",
            trigger: "#content-pmb.active",
        },
    ],
});
