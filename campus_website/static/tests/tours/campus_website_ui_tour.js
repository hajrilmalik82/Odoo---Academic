import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("campus_website_ui_tour", {
    url: "/web/login",
    steps: () => [
        {
            content: "Verify portfolio login panel and fill email",
            trigger: 'form.oe_login_form input[name="login"]',
            run: "edit zz.ui.website@contoh.test",
        },
        {
            content: "Fill password",
            trigger: 'form.oe_login_form input[name="password"]',
            run: "edit zz-ui-password",
        },
        {
            content: "Submit login form",
            trigger: 'form.oe_login_form button[type="submit"]',
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Verify Odoo webclient loaded cleanly",
            trigger: "body.o_web_client .o_main_navbar",
        },
    ],
});

registry.category("web_tour.tours").add("campus_website_portal_login_ui_tour", {
    url: "/web/login",
    steps: () => [
        {
            content: "Fill portal student login",
            trigger: 'form.oe_login_form input[name="login"]',
            run: "edit zz.ui.portal.web@contoh.test",
        },
        {
            content: "Fill portal student password",
            trigger: 'form.oe_login_form input[name="password"]',
            run: "edit zz-ui-password",
        },
        {
            content: "Submit login form",
            trigger: 'form.oe_login_form button[type="submit"]',
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Verify portal home loaded cleanly",
            trigger: ".o_portal_my_home",
        },
    ],
});

registry.category("web_tour.tours").add("campus_website_homepage_ui_tour", {
    url: "/",
    steps: () => [
        {
            content: "Verify header renders",
            trigger: "header",
        },
        {
            content: "Verify Core portfolio tab is active on homepage",
            trigger: "#tab-core",
            run: "click",
        },
        {
            content: "Verify Core tab content pane is active",
            trigger: "#content-core.active",
        },
        {
            content: "Verify footer renders",
            trigger: "footer",
        },
    ],
});
