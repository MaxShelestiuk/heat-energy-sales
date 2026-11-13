from odoo import http
from odoo.addons.portal.controllers.portal import CustomerPortal, pager
from odoo.exceptions import AccessError, MissingError
from odoo.http import request
from werkzeug.exceptions import NotFound


class HeatCustomerPortal(CustomerPortal):
    """Let signed-in customers read only their own issued heat bills."""

    def _heat_domain(self):
        """Build the ownership filter shared by every heat-bill portal route."""
        return [
            ("state", "=", "issued"),
            (
                "consumer_id.commercial_partner_id",
                "=",
                request.env.user.partner_id.commercial_partner_id.id,
            ),
        ]

    def _prepare_home_portal_values(self, counters):
        """Add the customer's heat-bill count when the portal asks for it."""
        values = super()._prepare_home_portal_values(counters)
        if "heat_bill_count" in counters:
            values["heat_bill_count"] = request.env["heat.bill"].search_count(self._heat_domain())
        return values

    @http.route(
        ["/my/heat-bills", "/my/heat-bills/page/<int:page>"], type="http", auth="user", website=True
    )
    def portal_heat_bills(self, page=1, **kw):
        """Show a paged list of the current customer's issued heat bills."""
        bills = request.env["heat.bill"]
        domain = self._heat_domain()
        values = self._prepare_portal_layout_values()
        pagination = pager(
            url="/my/heat-bills",
            total=bills.search_count(domain),
            page=page,
            step=self._items_per_page,
        )
        values.update(
            {
                "page_name": "heat_bills",
                "heat_bill": False,
                "heat_bills": bills.search(
                    domain,
                    order="period_start desc, id desc",
                    limit=self._items_per_page,
                    offset=pagination["offset"],
                ),
                "pager": pagination,
                "default_url": "/my/heat-bills",
            }
        )
        return request.render("heat_energy_sales.portal_heat_bills", values)

    @http.route("/my/heat-bills/<int:bill_id>", type="http", auth="user", website=True)
    def portal_heat_bill(self, bill_id, report_type=None, download=False, **kw):
        """Open or print one bill only after proving it belongs to this customer."""
        try:
            bill = request.env["heat.bill"].search(
                self._heat_domain() + [("id", "=", bill_id)], limit=1
            )
            if not bill:
                raise NotFound()
            bill.check_access("read")
        except (AccessError, MissingError) as error:
            raise NotFound() from error
        if report_type == "pdf":
            return self._show_report(
                bill, "pdf", "heat_energy_sales.action_report_heat_bill", download=bool(download)
            )
        values = self._prepare_portal_layout_values()
        # sudo is safe only after the ownership domain and read access above have
        # accepted the bill; it is needed solely for related labels in the page.
        values.update({"page_name": "heat_bills", "heat_bill": bill.sudo(), "heat_bills": False})
        return request.render("heat_energy_sales.portal_heat_bill", values)
