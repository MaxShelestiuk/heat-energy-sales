from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger
from psycopg2 import IntegrityError


@tagged("post_install", "-at_install")
class TestHeatMetering(TransactionCase):
    """Validate topology, historical readings and real controller isolation."""

    @classmethod
    def setUpClass(cls):
        """Build a contractual inlet and an independently owned object."""
        super().setUpClass()
        cls.category = cls.env["heat.consumer.category"].create(
            {"name": "Metering", "code": "METER_TEST"}
        )
        cls.payer = cls.env["res.partner"].create(
            {
                "name": "Hospital Test",
                "is_heat_consumer": True,
                "has_heat_contract": True,
                "heat_category_id": cls.category.id,
            }
        )
        cls.owner = cls.payer.copy({"name": "Pharmacy Test", "has_heat_contract": False})
        cls.node = cls.env["heat.supply.node"].create(
            {"name": "Test Inlet", "code": "INLET_TEST", "main_consumer_id": cls.payer.id}
        )
        cls.obj = cls.env["heat.supply.object"].create(
            {
                "name": "Test Building",
                "code": "BUILDING_TEST",
                "node_id": cls.node.id,
                "owner_id": cls.owner.id,
                "heated_volume_m3": 1000,
            }
        )
        cls.meter = cls.env["heat.meter"].create(
            {
                "name": "Main Test",
                "serial_number": "MAIN_TEST",
                "node_id": cls.node.id,
                "installation_date": "2026-01-01",
            }
        )
        cls.Reading = cls.env["heat.meter.reading"]

    def _reading(self, date, value, **values):
        """Create observations with real server-side controller defaults."""
        return self.Reading.create(
            {"meter_id": self.meter.id, "reading_date": date, "value": value, **values}
        )

    def test_node_contract_and_partner_edits(self):
        """The fallback payer cannot lose its contract through a partner edit."""
        with self.assertRaisesRegex(ValidationError, "active heat contract"), self.cr.savepoint():
            self.node.main_consumer_id = self.owner
        with self.assertRaisesRegex(ValidationError, "active heat contract"), self.cr.savepoint():
            self.payer.has_heat_contract = False
        self.assertEqual(self.node.main_meter_id, self.meter)

    @mute_logger("odoo.sql_db")
    def test_object_volume_and_payer(self):
        """Payer changes with the contract, while actual ownership stays intact."""
        self.assertEqual(self.obj.billing_consumer_id, self.payer)
        self.owner.has_heat_contract = True
        self.assertEqual(self.obj.billing_consumer_id, self.owner)
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.obj.heated_volume_m3 = 0
        with self.assertRaisesRegex(ValidationError, "object owner"), self.cr.savepoint():
            self.owner.write({"is_heat_consumer": False, "has_heat_contract": False})

    @mute_logger("odoo.sql_db")
    def test_meter_type_and_unique_assignment(self):
        """Only one active inlet/submeter can own each assignment."""
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.meter.copy({"serial_number": "DUP_MAIN"})
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.meter.write({"object_id": self.obj.id})
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.meter.write({"meter_type": "sub"})
        sub = self.meter.copy(
            {
                "name": "Submeter",
                "serial_number": "SUB_TEST",
                "meter_type": "sub",
                "object_id": self.obj.id,
            }
        )
        self.assertEqual(self.obj.meter_id, sub)
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            sub.copy({"serial_number": "DUP_SUB"})
        sub.active = False
        self.assertFalse(self.obj.meter_id)
        replacement = sub.copy({"serial_number": "NEW_SUB", "active": True})
        self.assertEqual(self.obj.meter_id, replacement)
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            sub.active = True

    def test_meter_and_object_node_consistency(self):
        """Both sides of a topology edit enforce the same inlet."""
        other = self.node.copy({"code": "OTHER_INLET"})
        with self.assertRaisesRegex(ValidationError, "same node"), self.cr.savepoint():
            self.meter.copy(
                {
                    "serial_number": "WRONG_SUB",
                    "meter_type": "sub",
                    "object_id": self.obj.id,
                    "node_id": other.id,
                }
            )
        self.meter.copy(
            {"serial_number": "VALID_SUB", "meter_type": "sub", "object_id": self.obj.id}
        )
        with self.assertRaisesRegex(ValidationError, "same node"), self.cr.savepoint():
            self.obj.node_id = other

    def test_reading_meter_selector_and_derived_company(self):
        """A new reading offers configured meters before it has a company."""
        field = self.Reading.fields_get(["meter_id"])["meter_id"]
        self.assertEqual(field["domain"], [])
        matches = self.env["heat.meter"].name_search("Main Test")
        self.assertIn(self.meter.id, [record_id for record_id, _name in matches])
        reading = self._reading("2026-10-01", 100)
        self.assertEqual(reading.company_id, self.meter.company_id)

    def test_cumulative_reading_order(self):
        """Backdated inserts and edits are checked against both neighbours."""
        first = self._reading("2026-10-01", 100)
        last = self._reading("2026-11-01", 200)
        middle = self._reading("2026-10-15", 150)
        for value in [99, 201]:
            with self.assertRaisesRegex(ValidationError, "cannot decrease"), self.cr.savepoint():
                middle.value = value
        with self.assertRaisesRegex(ValidationError, "cannot decrease"), self.cr.savepoint():
            self._reading("2026-10-20", 201)
        self.assertTrue(first.is_boundary_reading)
        self.assertTrue(last.is_boundary_reading)
        self.assertFalse(middle.is_boundary_reading)
        self.assertEqual(first.controller_user_id, self.meter.controller_user_id)
        self.assertEqual(last.value - first.value, 100)
        middle.unlink()
        self.assertEqual(len(self.meter.reading_ids), 2)

    def test_reading_navigation_and_consumption_aggregate(self):
        """Related topology is searchable and grouped consumption is a real delta."""
        first = self._reading("2026-10-01", 100)
        middle = self._reading("2026-10-15", 150)
        last = self._reading("2026-11-01", 200)
        self.assertEqual(last.node_id, self.node)
        self.assertFalse(last.object_id)
        self.assertEqual(middle.consumption_delta, 50)
        [group] = self.Reading._read_group(
            [("id", "in", (first | middle | last).ids)],
            ["meter_id"],
            ["consumption_delta:sum"],
        )
        self.assertEqual(group[0], self.meter)
        self.assertEqual(group[1], 100)

    @mute_logger("odoo.sql_db")
    def test_reading_date_unique_nonnegative_and_installation(self):
        """Invalid observations fail through ORM imports too."""
        self._reading("2026-10-01", 100)
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self._reading("2026-10-01", 100)
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self._reading("2026-09-01", -1)
        with self.assertRaisesRegex(ValidationError, "installation date"), self.cr.savepoint():
            self._reading("2025-12-31", 0)
        with self.assertRaisesRegex(ValidationError, "installation date"), self.cr.savepoint():
            self.meter.installation_date = "2026-11-01"
        with (
            self.assertRaisesRegex(ValidationError, "with readings cannot change"),
            self.cr.savepoint(),
        ):
            self.meter.write({"node_id": self.node.id})

    def _user(self, login, group):
        """Give users only explicit module roles for access assertions."""
        return self.env["res.users"].create(
            {
                "name": login,
                "login": login,
                "group_ids": [
                    Command.set([self.env.ref("heat_energy_sales.group_heat_" + group).id])
                ],
            }
        )

    def test_controller_and_admin_visibility(self):
        """Controller isolation limits reads and writes, with an admin override."""
        controller = self._user("heat_meter_controller", "controller")
        other = self._user("heat_meter_other", "controller")
        admin = self._user("heat_meter_admin", "admin")
        sales = self._user("heat_meter_sales", "sales")
        self.meter.controller_user_id = controller
        own = self._reading("2026-10-01", 100)
        foreign = self._reading("2026-11-01", 200, controller_user_id=other.id)
        domain = [("id", "in", (own | foreign).ids)]
        self.assertEqual(self.Reading.with_user(controller).search(domain), own)
        self.assertEqual(
            set(self.Reading.with_user(admin).search(domain).ids), {own.id, foreign.id}
        )
        self.assertEqual(len(self.Reading.with_user(sales).search(domain)), 2)
        with self.assertRaises(AccessError), self.cr.savepoint():
            foreign.with_user(controller).write({"note": "Unauthorized"})
        with self.assertRaises(AccessError), self.cr.savepoint():
            own.with_user(sales).write({"value": 110})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.meter.with_user(controller).write({"controller_user_id": other.id})
        with self.assertRaisesRegex(ValidationError, "cannot decrease"), self.cr.savepoint():
            self.Reading.with_user(controller).create(
                {"meter_id": self.meter.id, "reading_date": "2026-10-15", "value": 201}
            )
        created = self.Reading.with_user(controller).create(
            {"meter_id": self.meter.id, "reading_date": "2026-10-15", "value": 150}
        )
        self.assertEqual(created.controller_user_id, controller)
        with self.assertRaises(AccessError), self.cr.savepoint():
            created.write({"controller_user_id": other.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.meter.with_user(other).read(["name"])

    def test_cross_company_meter(self):
        """A meter cannot be attached to another supplier's node."""
        company = self.env["res.company"].create({"name": "Other Meter Supplier"})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.meter.write({"company_id": company.id})

    def test_derived_assignment_imports(self):
        """Readonly UI fields also reject inconsistent values over RPC."""
        with self.assertRaisesRegex(ValidationError, "meter form"), self.cr.savepoint():
            self.node.main_meter_id = False
        with self.assertRaisesRegex(ValidationError, "meter form"), self.cr.savepoint():
            self.obj.meter_id = self.meter
        with self.assertRaisesRegex(ValidationError, "owner's contract"), self.cr.savepoint():
            self.obj.billing_consumer_id = self.owner

    def test_hospital_demo_boundaries(self):
        """When demo is enabled its exact boundaries reproduce 100/30/10 Gcal."""
        node = self.env.ref("heat_energy_sales.node_hospital", raise_if_not_found=False)
        if not node:
            self.skipTest("Hospital demo is not installed in this database.")
        self.assertEqual(len(node.object_ids), 5)
        for key, expected in [("hospital", 100), ("block2", 30), ("pharmacy1", 10)]:
            start = self.env.ref("heat_energy_sales.reading_" + key + "_start")
            end = self.env.ref("heat_energy_sales.reading_" + key + "_end")
            self.assertEqual(end.value - start.value, expected)
        pharmacy_a = self.env.ref("heat_energy_sales.object_pharmacy1")
        pharmacy_b = self.env.ref("heat_energy_sales.object_pharmacy2")
        self.assertEqual(pharmacy_a.billing_consumer_id, node.main_consumer_id)
        self.assertEqual(pharmacy_b.billing_consumer_id, pharmacy_b.owner_id)
