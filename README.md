# Seatmap Pro seating for Odoo Events

This Odoo module lets buyers pick seats on a [Seatmap Pro](https://seatmap.pro) venue map when they register
for an event on your Odoo website. Tickets, prices, the cart, payment, and attendees stay in Odoo. Seatmap Pro
supplies the venue drawing and the map the buyer clicks on.

The technical name of the module is `seatmap_pro_event`. It depends on `website_event_sale`.

**Status:** early version for Odoo 19.0. The module's 40 tests pass on Odoo 19.0 Community (commit `4104bb5`).
With the module installed, the post-install tests of `event`, `event_sale`, `website_event`,
`website_event_sale`, and `website_sale` also pass. In a browser, the seat page loads the renderer and asks the
Seatmap Pro public API for the event. A full purchase in a browser against a real Seatmap Pro event is still
open.

## What you need

- You have a Seatmap Pro account. Its settings give you an organization token and a public key.
- The venue is drawn in the Seatmap Pro editor, and an event on that venue is published.
- You run Odoo 19.0 on your own server or on Odoo.sh, with the **Events** and **eCommerce** apps.
  Odoo Online cannot load modules that contain Python code, so this module does not work there.

## Install

1. Put the `seatmap_pro_event` folder into a directory on your Odoo `addons_path`.
2. Restart Odoo.
3. In **Apps**, select **Update Apps List**, search for **Seatmap Pro**, and select **Activate**.

The module needs only the Python packages that Odoo already installs.

On Odoo.sh, add this repository to your project as a Git submodule, or copy the folder into your project
repository. Odoo.sh builds the branch, and you activate the module in **Apps**.

## Connect Seatmap Pro

1. Go to **Events** > **Configuration** > **Settings**. You need the **Administration / Settings** access right.
2. In the **Seatmap Pro** block, paste the organization token and the public key.
3. Select **Save**.

The token field is write-only: Odoo stores the token and never sends it back to a browser, including the
administrator's. To replace the token, paste a new one.

## Set up an event

1. Open the event and go to the **Seatmap Pro** tab.
2. Enter the ID of the Seatmap Pro event and select **Load venue**. Odoo stores one record per seat, with its
   sector, row, and number.
3. Each Seatmap Pro pricing zone appears in the list below. Choose the Odoo ticket sold for each zone. Seats in
   a zone without a ticket are not for sale.

A seat keeps its record when you edit the venue in Seatmap Pro and load it again. If the new venue removes a
seat that is already booked, Odoo refuses the import and keeps the old seats.

On the same tab, **Seat hold (minutes)** sets how long a seat stays reserved for a buyer. The default is 15.

## What the buyer sees

On the event page, the **Register** button becomes **Choose seats** and opens the seat map. For an event with
several time slots, the buyer picks the slot first. Only seats that are free in Odoo can be selected, and they
show the price of the mapped ticket.

When the buyer continues, Odoo shows its usual attendee form with one attendee per seat. The seats go to the
cart as one order line per seat, and each attendee record keeps its seat. The seat appears on the order line,
in the attendee list, and on the attendee form in the back end.

Free tickets skip the cart, as they do in standard Odoo, and the attendees are confirmed at once.

## How seats are held

Standard Odoo keeps cart attendees in draft and does not count them against capacity. This module adds three
safeguards so that two buyers cannot get the same seat:

- A click on the map holds the seat on the server for the hold time. Another buyer cannot select it meanwhile.
- A scheduled action runs every minute. When a hold expires and the order is not being paid, it removes the
  seat's line and attendee from the cart and frees the seat.
- Before payment, Odoo checks every seat in the cart again. An expired hold is renewed if the seat is still
  free. If the seat is taken, the buyer cannot pay and is asked to choose another seat.

The database also refuses a second attendee for the same seat and slot, unless the first one is cancelled.

## Privacy and security notes

- The renderer is the published npm package `@seatmap.pro/renderer`, version 1.75.0. The seat page loads it
  from `cdn.jsdelivr.net`.
- The renderer reads the venue from the Seatmap Pro public API with the public key and the event ID.
- The organization token stays on your server. Only users with the **Administration / Settings** access right
  can change it, and no page or settings form sends it to a browser.
- The server sends the organization token only to `booking.seatmap.pro` over HTTPS and does not follow
  redirects. If you run Seatmap Pro on premise, the server administrator lists its Booking API host in the
  `SEATMAP_PRO_ALLOWED_API_HOSTS` environment variable, for example
  `SEATMAP_PRO_ALLOWED_API_HOSTS=seatmap.example.com`. The **Booking API** setting accepts only these hosts.
- Odoo 19.0 does not send a Content Security Policy for website pages. If your reverse proxy adds one, allow
  scripts from `https://cdn.jsdelivr.net`, connections to that host and to your Booking API host, and images
  over `https:` for the venue background.

## Limitations

- The module covers the website. Seat selection in Point of Sale and in back-end sales orders is not
  supported yet.
- The price on the map is the ticket's price. Pricelists and discounts apply in the cart.
- Standing areas from Seatmap Pro are not imported.
- A buyer can hold up to 30 seats at once, the Odoo limit for one registration.
- The module's own texts are in English.

## Odoo 20.0

The module targets 19.0. A 20.0 branch needs these changes:

- The pre-payment check moves from `_check_cart_is_ready_to_be_paid` to `_is_cart_ready_for_payment` in
  `sale.order`.
- Odoo 20.0 copies an attendee for each scan of a multi-use ticket. The seat field is not copied, so the copy
  does not conflict with the seat's unique index, but check-in reports should read the seat from the main
  attendee.
- Odoo 20.0 brings an abandoned cart back when the buyer signs in again. The pre-payment check covers seats
  that were released in the meantime.

The templates and controller methods that the module extends have the same names in 20.0.

## Security

Report security issues to hello@seatmap.pro and do not open a public issue for them.

## Development

Run the tests with Odoo's test runner on a database that has `website_event_sale` installed:

```bash
odoo-bin -d <database> -i seatmap_pro_event --test-enable --test-tags /seatmap_pro_event --stop-after-init
```

The tests replace the Booking API with a local fake, so they make no network calls.

## License

The module is licensed under the Apache License 2.0. Its manifest says `Other OSI approved licence`, because
the Odoo license list has no Apache-2.0 entry. The Seatmap Pro renderer and services are covered by the
[Seatmap Pro terms of service](https://seatmap.pro/tos/).
