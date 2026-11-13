from odoo import api, models
from odoo.fields import Command


class HeatBillDemo(models.Model):
    """Build the course demo by running the same workflow a real user runs."""

    _inherit = "heat.bill"

    @api.model
    def _load_course_demo(self):
        """Create the demo bills once when Odoo loads the optional demo XML."""
        if self.env.ref("heat_energy_sales.demo_bill_hospital_issued", raise_if_not_found=False):
            return
        node = self.env.ref("heat_energy_sales.node_hospital")
        company = node.company_id
        local = self.with_company(company)
        admin = self.env.ref("base.user_admin")
        admin.write(
            {
                "company_ids": [Command.link(company.id)],
                "group_ids": [Command.link(self.env.ref("heat_energy_sales.group_heat_admin").id)],
            }
        )
        company.heat_responsible_user_id = admin
        accounts = (
            self.env["account.account"]
            .with_company(company)
            .create(
                [
                    {
                        "name": "Heat Demonstration Revenue",
                        "code": "HDEMO700",
                        "account_type": "income",
                    },
                    {
                        "name": "Heat Demonstration Receivable",
                        "code": "HDEMO361",
                        "account_type": "asset_receivable",
                        "reconcile": True,
                    },
                ]
            )
        )
        revenue, receivable = accounts
        journal = (
            self.env["account.journal"]
            .with_company(company)
            .create(
                {
                    "name": "Heat Demonstration Sales",
                    "code": "HDEMO",
                    "type": "sale",
                    "company_id": company.id,
                    "default_account_id": revenue.id,
                    "sequence": 0,
                }
            )
        )
        product = (
            self.env["product.product"]
            .with_company(company)
            .create(
                {
                    "name": "Heat Energy Demonstration",
                    "type": "service",
                    "company_id": company.id,
                    "property_account_income_id": revenue.id,
                    "taxes_id": [Command.clear()],
                }
            )
        )
        company.heat_service_product_id = product
        consumers = self.env["res.partner"].browse(
            [
                self.env.ref("heat_energy_sales." + name).id
                for name in ("hospital", "pharmacy_a", "pharmacy_b", "school", "church")
            ]
        )
        consumers.with_company(company).property_account_receivable_id = receivable
        all_nodes = (
            node
            | self.env.ref("heat_energy_sales.node_school")
            | self.env.ref("heat_energy_sales.node_church")
        )
        # Using the public calculation flow here keeps the demo honest: a broken
        # allocation or transition makes installation fail instead of hiding it.
        bills = local._generate(company, "2026-10-01", nodes=all_nodes)
        hospital = bills.filtered(
            lambda bill: bill.consumer_id == self.env.ref("heat_energy_sales.hospital")
        )
        pharmacy = bills.filtered(
            lambda bill: bill.consumer_id == self.env.ref("heat_energy_sales.pharmacy_b")
        )
        school = bills.filtered(
            lambda bill: bill.consumer_id == self.env.ref("heat_energy_sales.school")
        )
        church = bills - hospital - pharmacy - school
        for bill in hospital | pharmacy | school:
            bill.action_approve()
            bill.action_issue()
        november = local._generate(
            company, "2026-11-01", nodes=self.env.ref("heat_energy_sales.node_school")
        )
        november.action_approve()
        draft = local.create(
            {
                "consumer_id": church.consumer_id.id,
                "company_id": company.id,
                "period_start": "2026-11-01",
            }
        )
        cancelled = local.create(
            {
                "consumer_id": church.consumer_id.id,
                "company_id": company.id,
                "period_start": "2026-12-01",
                "cancellation_reason": "Demonstration of a cancelled monthly document",
            }
        )
        cancelled.action_cancel()
        portal = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Hospital Consumer",
                    "login": "heat.hospital.portal",
                    "partner_id": hospital.consumer_id.id,
                    "company_id": company.id,
                    "company_ids": [Command.set(company.ids)],
                    "group_ids": [Command.set(self.env.ref("base.group_portal").ids)],
                }
            )
        )
        # Dynamic workflow records need external ids too, otherwise they are hard
        # to reuse in tests and Odoo cannot clean them up during module uninstall.
        records = {
            "demo_revenue": revenue,
            "demo_receivable": receivable,
            "demo_journal": journal,
            "demo_product": product,
            "demo_portal_user": portal,
            "demo_bill_hospital_issued": hospital,
            "demo_bill_pharmacy_issued": pharmacy,
            "demo_bill_school_issued": school,
            "demo_bill_church_calculated": church,
            "demo_bill_school_approved": november,
            "demo_bill_church_draft": draft,
            "demo_bill_church_cancelled": cancelled,
        }
        for bill in bills | november:
            records.update({f"demo_line_{bill.id}_{line.id}": line for line in bill.line_ids})
            if bill.account_move_id:
                records[f"demo_invoice_{bill.id}"] = bill.account_move_id
                records.update(
                    {
                        f"demo_invoice_line_{bill.id}_{line.id}": line
                        for line in bill.account_move_id.line_ids
                    }
                )
        self.env["ir.model.data"].create(
            [
                {
                    "module": "heat_energy_sales",
                    "name": name,
                    "model": record._name,
                    "res_id": record.id,
                    "noupdate": True,
                }
                for name, record in records.items()
            ]
        )
