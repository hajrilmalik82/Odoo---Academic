/**
 * Website frontend interactions for Campus Website.
 *
 * 1. CampusWebsiteChrome: rewrites header#top tel: links to WhatsApp at runtime
 *    and cleanly restores original DOM state on destroy so Website Builder
 *    Edit/Save never persists mutated markup into ir.ui.view.
 * 2. CampusDemoLogin: handles optional portfolio reviewer demo-login buttons
 *    using form.requestSubmit() so HTML5 validation, CSRF, and anti-bot hooks
 *    remain intact without inline onclick handlers.
 */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

const WHATSAPP_URL = "https://wa.me/6281178783903";
const WHATSAPP_DISPLAY = "081178783903";

export class CampusWebsiteChrome extends Interaction {
    static selector = "header#top";

    start() {
        this.rewritePhoneLinks();
    }

    rewritePhoneLinks() {
        for (const link of this.el.querySelectorAll('a[href^="tel:"]')) {
            const snapshot = {
                href: link.getAttribute("href"),
                target: link.getAttribute("target"),
                rel: link.getAttribute("rel"),
                hadTextSuccess: link.classList.contains("text-success"),
                hadFwBold: link.classList.contains("fw-bold"),
                children: Array.from(link.childNodes),
            };

            link.href = WHATSAPP_URL;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.classList.add("text-success", "fw-bold");

            const icon = document.createElement("i");
            icon.className = "fa fa-whatsapp text-success me-1";
            icon.setAttribute("aria-hidden", "true");
            const label = document.createElement("span");
            label.textContent = WHATSAPP_DISPLAY;
            link.replaceChildren(icon, label);

            this.registerCleanup(() => {
                if (snapshot.href === null) {
                    link.removeAttribute("href");
                } else {
                    link.setAttribute("href", snapshot.href);
                }
                if (snapshot.target === null) {
                    link.removeAttribute("target");
                } else {
                    link.setAttribute("target", snapshot.target);
                }
                if (snapshot.rel === null) {
                    link.removeAttribute("rel");
                } else {
                    link.setAttribute("rel", snapshot.rel);
                }
                if (!snapshot.hadTextSuccess) {
                    link.classList.remove("text-success");
                }
                if (!snapshot.hadFwBold) {
                    link.classList.remove("fw-bold");
                }
                link.replaceChildren(...snapshot.children);
            });
        }
    }
}

export class CampusDemoLogin extends Interaction {
    static selector = ".campus-demo-login-btn";
    dynamicContent = {
        _root: {
            "t-on-click": this.onClickDemoLogin,
        },
    };

    onClickDemoLogin() {
        const form = document.querySelector("form.oe_login_form");
        if (!form) {
            return;
        }
        const loginInput = form.querySelector('input[name="login"]');
        const passwordInput = form.querySelector('input[name="password"]');
        if (!loginInput || !passwordInput) {
            return;
        }
        loginInput.value = this.el.dataset.demoLogin || "";
        passwordInput.value = this.el.dataset.demoPassword || "";
        if (typeof form.requestSubmit === "function") {
            form.requestSubmit();
        } else {
            form.submit();
        }
    }
}

registry.category("public.interactions").add("campus_website.chrome", CampusWebsiteChrome);
registry.category("public.interactions").add("campus_website.demo_login", CampusDemoLogin);
