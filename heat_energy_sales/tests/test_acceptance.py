from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common_billing import HeatBillingCase


@tagged("post_install", "-at_install")
class TestHeatAcceptance(HeatBillingCase):
    """Verify demo completeness and isolation of unrelated source nodes."""

    def test_unrelated_nodes_do_not_share_source_locks(self):
        """Approving one node must not freeze a disconnected node's readings."""
        consumer = self.hospital.copy({"name": "Independent consumer"})
        node = self.node.copy({"code": "INDEPENDENT", "main_consumer_id": consumer.id})
        self.env["heat.supply.object"].create(
            {
                "name": "Independent",
                "code": "INDEPENDENT",
                "node_id": node.id,
                "owner_id": consumer.id,
                "heated_volume_m3": 100,
            }
        )
        meter = self.env["heat.meter"].create(
            {
                "name": "Independent",
                "serial_number": "INDEPENDENT",
                "node_id": node.id,
                "meter_type": "main",
                "installation_date": "2026-01-01",
            }
        )
        readings = self.env["heat.meter.reading"].create(
            [
                {"meter_id": meter.id, "reading_date": date, "value": value}
                for date, value in [("2026-10-01", 10), ("2026-11-01", 20)]
            ]
        )
        bills = self.Bill._generate(self.env.company, self.period, nodes=self.node | node)
        hospital = bills.filtered(lambda bill: bill.consumer_id == self.hospital)
        independent = bills.filtered(lambda bill: bill.consumer_id == consumer)
        self.assertFalse(hospital.source_reading_ids & readings)
        self.assertEqual(independent.source_reading_ids, readings)
        hospital.action_approve()
        readings[-1].value = 21
        with self.assertRaises(UserError):
            independent.action_approve()

    def test_uninstall_flag_is_not_a_user_bypass(self):
        """A forged cleanup context cannot remove approved billing evidence."""
        bills = self._calculate()
        bills.action_approve()
        admin = self._user("cleanup_flag_admin", "admin")
        protected_records = (
            (bills[:1], UserError),
            (bills.line_ids[:1], UserError),
            (bills.source_reading_ids[:1], ValidationError),
        )
        for record, error in protected_records:
            with self.assertRaises(error), self.cr.savepoint():
                record.with_user(admin).with_context(_force_unlink=True).unlink()

    def test_demo_workflow(self):
        """Optional demonstration records are coherent and use unposted invoices."""
        hospital = self.env.ref("heat_energy_sales.demo_bill_hospital_issued", False)
        if not hospital:
            self.skipTest("Demo data is not installed")
        company = hospital.company_id
        bills = self.Bill.search([("company_id", "=", company.id)])
        self.assertEqual(len(bills), 7)
        self.assertEqual(
            set(bills.mapped("state")), {"draft", "calculated", "approved", "issued", "cancelled"}
        )
        self.assertEqual(hospital.energy_total_gcal, 85)
        pharmacy = self.env.ref("heat_energy_sales.demo_bill_pharmacy_issued")
        self.assertEqual(pharmacy.energy_total_gcal, 15)
        self.assertEqual(len(bills.account_move_id), 3)
        self.assertEqual(set(bills.account_move_id.mapped("state")), {"draft"})
