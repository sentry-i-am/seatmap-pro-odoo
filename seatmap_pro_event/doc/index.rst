==============================
Seatmap Pro Seating for Events
==============================

Buyers pick seats on a Seatmap Pro venue map when they register for an event on the Odoo website.

Requirements
============

* A Seatmap Pro account with an organization token and a public key.
* A venue drawn in the Seatmap Pro editor and a published event on that venue.
* Odoo with the Events and eCommerce apps, on your own server or on Odoo.sh.

Configuration
=============

#. Go to **Events > Configuration > Settings**. In the **Seatmap Pro** block, paste the organization token
   and the public key, then select **Save**. You need the **Administration / Settings** access right.
#. Open the event and go to the **Seatmap Pro** tab.
#. Enter the ID of the Seatmap Pro event and select **Load venue**.
#. Choose the Odoo ticket sold for each pricing zone.

**Seat hold (minutes)** on the same tab sets how long a seat stays reserved for a buyer. The default is 15.

If you run Seatmap Pro on premise, the server administrator lists its Booking API host in the
``SEATMAP_PRO_ALLOWED_API_HOSTS`` environment variable. The **Booking API** setting accepts only these hosts.

Usage
=====

On the event page, the **Register** button becomes **Choose seats** and opens the map. The buyer selects seats,
fills in one attendee per seat, and pays through the standard Odoo checkout. Each seat is its own cart line and
its own attendee.

The full guide, including the security notes and limitations, is in the README of the
`source repository <https://github.com/sentry-i-am/seatmap-pro-odoo>`_.
