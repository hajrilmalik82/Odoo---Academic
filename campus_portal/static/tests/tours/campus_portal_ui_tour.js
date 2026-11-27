import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("campus_portal_student_ui_tour", {
    url: "/my",
    steps: () => [
        {
            content: "Open Study Plans (KRS) from portal home",
            trigger: 'a[href="/my/krs"]',
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Open student KRS detail page",
            trigger: 'a[href^="/my/krs/"]',
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Verify KRS detail page and Print button rendered cleanly",
            trigger: 'a[href*="/report?download=1"]',
        },
    ],
});

registry.category("web_tour.tours").add("campus_portal_krs_register_add_remove_submit_ui_tour", {
    url: "/my/krs",
    steps: () => [
        {
            content: "Register new KRS for current term",
            trigger: 'form[action="/my/krs/register"] button[type="submit"]',
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Add available course line to draft KRS",
            trigger: 'form[action$="/add_line"] button[type="submit"]',
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Remove course line from draft KRS",
            trigger: 'form[action*="/delete_line/"] button[type="submit"]',
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Re-add course line to draft KRS",
            trigger: 'form[action$="/add_line"] button[type="submit"]',
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Submit KRS to Academic Advisor",
            trigger: 'form[action$="/submit"] button[type="submit"]',
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Verify KRS submitted badge rendered",
            trigger: '.badge.text-bg-info:contains("Waiting for Approval")',
        },
    ],
});

registry.category("web_tour.tours").add("campus_portal_khs_transcript_ui_tour", {
    url: "/my",
    steps: () => [
        {
            content: "Open Academic Results (KHS) from portal home",
            trigger: 'a[href="/my/khs"]',
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Verify KHS report download link rendered",
            trigger: 'a[href*="/report?download=1"]',
        },
        {
            content: "Verify Official Transcript download link rendered",
            trigger: 'a[href*="/transcript?download=1"]',
        },
    ],
});

registry.category("web_tour.tours").add("campus_portal_homepage_tab_ui_tour", {
    url: "/",
    steps: () => [
        {
            content: "Click Student Portal portfolio tab on homepage",
            trigger: "#tab-portal",
            run: "click",
        },
        {
            content: "Verify Student Portal tab pane becomes active",
            trigger: "#content-portal.active",
        },
    ],
});
