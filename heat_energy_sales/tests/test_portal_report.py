from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests import HttpCase, tagged

from .common_billing import HeatInvoiceCase


@tagged("post_install", "-at_install")
class TestHeatPortalReport(HeatInvoiceCase, HttpCase):
    """Test the actual portal HTTP surface and report access boundary."""

    @classmethod
    def setUpClass(cls):
        """Issue both hospital documents and give only the hospital a portal login."""
        super().setUpClass()
        cls.bills = cls.Bill._generate(cls.env.company, cls.period, nodes=cls.node)
        cls.bills.action_approve()
        for bill in cls.bills:
            bill.action_issue()
        cls.own = cls.bills.filtered(lambda bill: bill.consumer_id == cls.hospital)
        cls.foreign = cls.bills - cls.own
        cls.draft = cls.Bill.create({"consumer_id": cls.hospital.id, "period_start": "2026-11-01"})
        cls.portal_user = (
            cls.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Hospital Portal Test",
                    "login": "heat_portal_test",
                    "password": "portal-test-only",
                    "partner_id": cls.hospital.id,
                    "group_ids": [Command.set(cls.env.ref("base.group_portal").ids)],
                }
            )
        )

    def test_portal_orm_isolation_and_audit_privacy(self):
        """Read ACLs reveal only own issued bills and never the node-wide audit."""
        Bill = self.Bill.with_user(self.portal_user)
        self.assertEqual(Bill.search([("id", "in", (self.bills | self.draft).ids)]), self.own)
        with self.assertRaises(AccessError):
            self.foreign.with_user(self.portal_user).read(["name"])
        with self.assertRaises(AccessError):
            self.own.with_user(self.portal_user).read(["calculation_log"])
        with self.assertRaises(AccessError):
            self.foreign.line_ids.with_user(self.portal_user).read(["quantity_gcal"])
        with self.assertRaises(AccessError):
            self.own.with_user(self.portal_user).write({"cancellation_reason": "Forbidden"})

    def test_portal_http_list_detail_pdf(self):
        """Logged-in customers can view and download only their issued bills."""
        self.authenticate("heat_portal_test", "portal-test-only")
        response = self.url_open("/my/heat-bills")
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.own.name, response.text)
        self.assertNotIn(self.foreign.name, response.text)
        self.assertNotIn(self.draft.name, response.text)
        response = self.url_open(f"/my/heat-bills/{self.own.id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Pharmacy A", response.text)
        self.assertIn("Download PDF", response.text)
        response = self.url_open(f"/my/heat-bills/{self.own.id}?report_type=pdf&download=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/pdf")
        # Odoo intentionally substitutes HTML for wkhtmltopdf during HTTP tests.
        # The acceptance script separately renders and inspects the actual PDF.
        self.assertIn(self.own.name.encode(), response.content)
        for bill in self.foreign | self.draft:
            response = self.url_open(
                f"/my/heat-bills/{bill.id}?report_type=pdf&access_token=forged"
            )
            self.assertEqual(response.status_code, 404)

    def test_report_direct_endpoint_cannot_bypass_owner(self):
        """The generic report route also validates each document before sudo."""
        report = self.env["ir.actions.report"].with_user(self.portal_user)
        own_html = report._render_qweb_html(
            "heat_energy_sales.action_report_heat_bill", self.own.ids
        )[0]
        self.assertIn(self.own.name.encode(), own_html)
        with self.assertRaises(AccessError):
            report._render_qweb_html("heat_energy_sales.action_report_heat_bill", self.foreign.ids)
        with self.assertRaises(AccessError):
            report._render_qweb_html("heat_energy_sales.action_report_heat_bill", self.bills.ids)

    def test_batch_report_and_all_backend_views(self):
        """Each selected bill has its own report article and views compile."""
        from lxml import html

        content = self.env["ir.actions.report"]._render_qweb_html(
            "heat_energy_sales.action_report_heat_bill", (self.bills | self.draft).ids
        )[0]
        self.assertNotIn(b"The accounting invoice applies", content)
        self.assertEqual(self.env.ref("heat_energy_sales.paperformat_heat_bill").header_spacing, 8)
        document = html.fromstring(content)
        self.assertEqual(len(document.xpath('//div[contains(@class, "article")]')), 3)
        self.assertEqual(len(document.xpath('//div[@class="header"]')), 3)
        self.assertEqual(len(document.xpath('//div[@class="footer"]')), 3)
        for model in [
            "heat.consumer.category",
            "heat.tariff",
            "heat.supply.node",
            "heat.supply.object",
            "heat.meter",
            "heat.meter.reading",
            "heat.bill",
            "heat.bill.line",
        ]:
            for view_type in ["list", "form"]:
                self.assertTrue(self.env[model].get_view(view_type=view_type)["arch"])
        for view_type in ["search", "kanban", "pivot", "graph"]:
            self.assertTrue(self.Bill.get_view(view_type=view_type)["arch"])
