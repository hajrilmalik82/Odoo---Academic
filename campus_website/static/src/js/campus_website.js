/**
 * Website chrome that cannot be expressed in the template.
 *
 * Rewrites the header tel: link to WhatsApp after the stock header has rendered.
 */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class CampusWebsiteChrome extends Interaction {
    static selector = "header";

    start() {
        this.rewritePhoneLinks();
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
}

registry.category("public.interactions").add("campus_website.chrome", CampusWebsiteChrome);
