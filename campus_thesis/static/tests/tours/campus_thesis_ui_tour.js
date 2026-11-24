import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("campus_thesis_portal_ui_tour", {
    url: "/my/thesis",
    steps: () => [
        {
            content: "Verify Thesis portal breadcrumb and page loaded",
            trigger: 'ol.o_portal_submenu li:contains("My Thesis")',
        },
    ],
});

registry.category("web_tour.tours").add("campus_thesis_create_update_submit_ui_tour", {
    url: "/my/thesis",
    steps: () => [
        {
            content: "Fill thesis title on registration form",
            trigger: 'form[action="/my/thesis/create"] input[name="title"]',
            run: "edit ZZTEST Implementasi Sistem Akademik UI",
        },
        {
            content: "Select primary supervisor",
            trigger: 'form[action="/my/thesis/create"] select[name="supervisor_id"]',
            run: () => {
                const sel = document.querySelector('form[action="/my/thesis/create"] select[name="supervisor_id"]');
                const opt = Array.from(sel.options).find((o) => o.value);
                if (!opt) {
                    throw new Error("No primary supervisor option available.");
                }
                sel.value = opt.value;
                sel.dispatchEvent(new Event("change", { bubbles: true }));
            },
        },
        {
            content: "Submit create thesis form",
            trigger: 'form[action="/my/thesis/create"] button[type="submit"]',
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Update thesis title on detail page",
            trigger: 'form[action$="/update"] input[name="title"]',
            run: "edit ZZTEST Implementasi Sistem Akademik UI v2",
        },
        {
            content: "Save updated draft thesis",
            trigger: 'form[action$="/update"] button[type="submit"]',
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Submit thesis for supervisor approval",
            trigger: 'form[action$="/submit"] button[type="submit"]',
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Verify thesis detail page shows updated state",
            trigger: 'a[href*="/report?download=1"]',
        },
    ],
});

registry.category("web_tour.tours").add("campus_thesis_progress_log_ui_tour", {
    steps: () => [
        {
            content: "Fill progress milestone",
            trigger: 'form[action$="/add_progress"] input[name="milestone"]',
            run: "edit Chapter 1 - Introduction",
        },
        {
            content: "Fill progress description",
            trigger: 'form[action$="/add_progress"] textarea[name="description"]',
            run: "edit Initial draft reviewed in UI tour.",
        },
        {
            content: "Submit progress log",
            trigger: 'form[action$="/add_progress"] button[type="submit"]',
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Verify progress milestone rendered on thesis page",
            trigger: ':contains("Chapter 1 - Introduction")',
        },
    ],
});

registry.category("web_tour.tours").add("campus_thesis_list_to_form_ui_tour", {
    steps: () => [
        {
            content: "Open first record from list view",
            trigger: ".o_list_view .o_data_row td.o_data_cell",
            run: "click",
        },
        {
            content: "Verify form sheet rendered cleanly",
            trigger: ".o_form_view .o_form_sheet",
        },
    ],
});

registry.category("web_tour.tours").add("campus_thesis_list_only_ui_tour", {
    steps: () => [
        {
            content: "Verify inline-editable thesis requirement list view renders rows cleanly",
            trigger: ".o_list_view .o_data_row",
        },
    ],
});

registry.category("web_tour.tours").add("campus_thesis_homepage_tab_ui_tour", {
    url: "/",
    steps: () => [
        {
            content: "Click Final Thesis portfolio tab on homepage",
            trigger: "#tab-thesis",
            run: "click",
        },
        {
            content: "Verify Final Thesis tab pane becomes active",
            trigger: "#content-thesis.active",
        },
    ],
});
