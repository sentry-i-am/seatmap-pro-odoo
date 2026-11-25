import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

/**
 * Shows the Seatmap Pro venue map and sends the chosen seats into the standard Odoo
 * registration flow. Only seats that Odoo lists as free can be selected. Each click
 * holds the seat on the server, so two buyers cannot take the same seat.
 */
export class SeatmapSeatPicker extends Interaction {
    static selector = ".o_seatmap_pro_picker";
    dynamicContent = {
        ".o_seatmap_pro_submit": {
            "t-on-click.prevent.stop": this.onSubmitClick,
            "t-att-disabled": () => (this.selected.size === 0 || this.busy ? "disabled" : false),
        },
        ".o_seatmap_pro_summary": {
            "t-out": () => this.summary,
        },
    };

    setup() {
        this.config = JSON.parse(this.el.dataset.seatmapConfig);
        this.seats = new Map(Object.entries(this.config.seats).map(([id, seat]) => [Number(id), seat]));
        this.selected = new Map();
        this.busy = false;
        this.format = new Intl.NumberFormat(document.documentElement.lang || undefined, {
            style: "currency",
            currency: this.config.currency,
        });
    }

    async willStart() {
        const { SeatmapBookingRenderer } = await import(this.config.rendererUrl);
        this.renderer = new SeatmapBookingRenderer(this.el.querySelector(".o_seatmap_pro_map"), {
            publicKey: this.config.publicKey,
            baseUrl: this.config.apiUrl,
            lockedSeatsFilter: (seat) => !this.seats.has(seat.id),
            onSeatSelect: (seat) => this.onSeatSelect(seat),
            onSeatDeselect: (seat) => this.onSeatDeselect(seat),
        });
        await this.renderer.loadEvent(this.config.eventId);
        this.renderer.setExternalPrices(
            [...this.seats.entries()].map(([id, seat]) => ({
                id,
                seatKey: "",
                price: seat.price,
                priceId: seat.ticketId,
            }))
        );
        this.renderer.updateSeatLocks((seat) => !this.seats.has(seat.id));
    }

    get summary() {
        if (!this.selected.size) {
            return "";
        }
        const total = [...this.selected.values()].reduce((sum, seat) => sum + seat.price, 0);
        return this.config.labels.selected
            .replace("{count}", this.selected.size)
            .replace("{total}", this.format.format(total));
    }

    showMessage(text) {
        const messageEl = this.el.querySelector(".o_seatmap_pro_message");
        messageEl.textContent = text;
        messageEl.classList.toggle("d-none", !text);
    }

    lock(seatIds, release = false) {
        return rpc(this.config.lockUrl, {
            seat_ids: seatIds,
            slot_id: this.config.slotId,
            release,
        });
    }

    /**
     * Seats that the server refused are removed from the map's free seats.
     */
    markTaken(seatIds) {
        const labels = seatIds.map((id) => this.seats.get(id)?.label || String(id)).join(", ");
        for (const id of seatIds) {
            this.seats.delete(id);
            this.selected.delete(id);
        }
        this.renderer.updateSeatLocks((seat) => !this.seats.has(seat.id));
        this.showMessage(this.config.labels.taken.replace("{seats}", labels));
        this.updateContent();
    }

    onSeatSelect(seat) {
        const seatData = this.seats.get(seat.id);
        if (!seatData) {
            return false;
        }
        if (this.selected.size >= this.config.maxSeats) {
            this.showMessage(this.config.labels.tooMany.replace("{max}", this.config.maxSeats));
            return false;
        }
        this.selected.set(seat.id, seatData);
        this.showMessage("");
        this.updateContent();
        this.waitFor(this.lock([seat.id])).then((result) => {
            if (result.taken.length) {
                this.markTaken(result.taken);
            }
        });
        return true;
    }

    onSeatDeselect(seat) {
        this.selected.delete(seat.id);
        this.updateContent();
        this.waitFor(this.lock([seat.id], true));
        return true;
    }

    async onSubmitClick() {
        this.busy = true;
        this.updateContent();
        try {
            const params = { seatmap_seat_ids: [...this.selected.keys()].join(",") };
            if (this.config.slotId) {
                params.event_slot_id = this.config.slotId;
            }
            const result = await this.waitFor(rpc(this.config.registrationUrl, params));
            if (typeof result === "string") {
                const modalEl = new DOMParser().parseFromString(result, "text/html").body.firstChild;
                this.insert(modalEl, document.body);
            } else if (result && result.taken) {
                this.markTaken(result.taken);
            }
        } finally {
            this.busy = false;
            this.updateContent();
        }
    }
}

registry.category("public.interactions").add("seatmap_pro_event.seat_picker", SeatmapSeatPicker);
