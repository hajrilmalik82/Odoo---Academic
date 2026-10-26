/**
 * Website chrome that cannot be expressed in the template.
 *
 * This was an inline <script> in the website.layout override. Two of the three
 * things it did have been removed rather than moved:
 *
 *  - Renaming the Home menu is done once, in post_init_hook. Doing it again
 *    here meant the real mechanism could break and nobody would notice,
 *    because the JS covered it.
 *  - The styles moved to static/src/scss/campus_website.scss.
 *
 * What is left is genuinely client-side: website.menu carries no group or
 * audience field, so the admission entry cannot be hidden from signed-in users
 * declaratively, and the phone link is rewritten to WhatsApp after the stock
 * header has rendered it.
 */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class CampusWebsiteChrome extends Interaction {
    static selector = "header";

    start() {
        this.rewritePhoneLinks();
        this.hideAdmissionMenuWhenSignedIn();
    }

    rewritePhoneLinks() {
        for (const link of this.el.querySelectorAll('a[href^="tel:"]')) {
            link.href = "https://wa.me/6281178783903";
            link.target = "_blank";
            link.classList.add("text-success", "fw-bold");
            link.innerHTML =
                '<i class="fa fa-whatsapp text-success me-1"></i><span>081178783903</span>';
        }
    }

    hideAdmissionMenuWhenSignedIn() {
        const signedIn =
            this.el.querySelector('a[href*="/web/session/logout"]') ||
            this.el.querySelector(".o_user_menu") ||
            this.el.querySelector('a[href="/my/home"]');
        if (!signedIn) {
            return;
        }
        const admissionLink = this.el.querySelector('a[href*="/admission"]');
        if (admissionLink && admissionLink.parentElement) {
            admissionLink.parentElement.style.display = "none";
        }
    }
}

registry.category("public.interactions").add("campus_website.chrome", CampusWebsiteChrome);
