from odoo.fields import Command
from odoo.tests import TransactionCase


class HeatBillingCase(TransactionCase):
    """Hospital fixture independent of optional module demo records."""

    @classmethod
    def setUpClass(cls):
        """Build the specified five-object hospital and exact month boundaries."""
        super().setUpClass()
        cls.Bill = cls.env["heat.bill"]
        cls.period = "2026-10-01"
        cls.budget, cls.other = cls.env["heat.consumer.category"].create(
            [
                {"name": "Budget Test", "code": "BILL_BUDGET"},
                {"name": "Other Test", "code": "BILL_OTHER"},
            ]
        )
        cls.tariffs = cls.env["heat.tariff"].create(
            [
                {"category_id": cls.budget.id, "date_from": "2026-01-01", "price_per_gcal": 1500},
                {"category_id": cls.other.id, "date_from": "2026-01-01", "price_per_gcal": 2000},
            ]
        )
        cls.hospital, cls.pharmacy_a, cls.pharmacy_b = cls.env["res.partner"].create(
            [
                {
                    "name": "Hospital Billing Test",
                    "is_heat_consumer": True,
                    "heat_category_id": cls.budget.id,
                    "has_heat_contract": True,
                },
                {
                    "name": "Pharmacy A Billing Test",
                    "is_heat_consumer": True,
                    "heat_category_id": cls.other.id,
                },
                {
                    "name": "Pharmacy B Billing Test",
                    "is_heat_consumer": True,
                    "heat_category_id": cls.other.id,
                    "has_heat_contract": True,
                },
            ]
        )
        cls.node = cls.env["heat.supply.node"].create(
            {
                "name": "Hospital Billing Test",
                "code": "BILL_NODE",
                "main_consumer_id": cls.hospital.id,
            }
        )
        cls.objects = cls.env["heat.supply.object"].create(
            [
                {
                    "name": name,
                    "code": "BILL_" + str(index),
                    "node_id": cls.node.id,
                    "owner_id": owner.id,
                    "heated_volume_m3": volume,
                }
                for index, (name, owner, volume) in enumerate(
                    [
                        ("Block 1", cls.hospital, 2000),
                        ("Lab", cls.hospital, 1000),
                        ("Block 2", cls.hospital, 1500),
                        ("Pharmacy A", cls.pharmacy_a, 200),
                        ("Pharmacy B", cls.pharmacy_b, 1000),
                    ]
                )
            ]
        )
        cls.meters = cls.env["heat.meter"].create(
            [
                {
                    "name": name,
                    "serial_number": "BILL_" + name,
                    "node_id": cls.node.id,
                    "meter_type": kind,
                    "object_id": obj.id if obj else False,
                    "installation_date": "2026-01-01",
                }
                for name, kind, obj in [
                    ("Main", "main", False),
                    ("Block2", "sub", cls.objects[2]),
                    ("PharmacyA", "sub", cls.objects[3]),
                ]
            ]
        )
        cls.readings = cls.env["heat.meter.reading"].create(
            [
                {"meter_id": meter.id, "reading_date": date, "value": value}
                for meter, start, end in zip(
                    cls.meters, [1000, 200, 50], [1100, 230, 60], strict=True
                )
                for date, value in [
                    ("2026-10-01", start),
                    ("2026-10-15", (start + end) / 2),
                    ("2026-11-01", end),
                ]
            ]
        )

    def _calculate(self):
        """Exercise the public form button and return all companion documents."""
        bill = self.Bill.create({"consumer_id": self.hospital.id, "period_start": self.period})
        action = bill.action_calculate()
        return self.Bill.search(action["domain"])

    def _user(self, login, group):
        """Create an internal user with exactly the requested functional role."""
        return self.env["res.users"].create(
            {
                "name": login,
                "login": login,
                "group_ids": [
                    Command.set([self.env.ref("heat_energy_sales.group_heat_" + group).id])
                ],
            }
        )


class HeatInvoiceCase(HeatBillingCase):
    """Reusable real accounting configuration for invoice and portal tests."""

    @classmethod
    def setUpClass(cls):
        """Configure real accounting accounts, a sales journal and a taxed service."""
        super().setUpClass()
        cls.env.company.country_id = cls.env.ref("base.us")
        income, receivable = cls.env["account.account"].create(
            [
                {"name": "Heat Test Revenue", "code": "HEAT.REV", "account_type": "income"},
                {
                    "name": "Heat Test Receivable",
                    "code": "HEAT.REC",
                    "account_type": "asset_receivable",
                    "reconcile": True,
                },
            ]
        )
        cls.journal = cls.env["account.journal"].create(
            {
                "name": "Heat Test Sales",
                "code": "HEAT",
                "type": "sale",
                "company_id": cls.env.company.id,
                "default_account_id": income.id,
                "sequence": 0,
            }
        )
        (cls.hospital | cls.pharmacy_a | cls.pharmacy_b).property_account_receivable_id = receivable
        cls.tax = cls.env["account.tax"].create(
            {
                "name": "Heat Test 20%",
                "amount": 20,
                "amount_type": "percent",
                "type_tax_use": "sale",
                "company_id": cls.env.company.id,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Heat Test Service",
                "type": "service",
                "property_account_income_id": income.id,
                "taxes_id": [Command.set(cls.tax.ids)],
            }
        )
        cls.env.company.heat_service_product_id = cls.product
        cls.Wizard = cls.env["heat.bill.generate.wizard"]
