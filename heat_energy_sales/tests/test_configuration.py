from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger
from psycopg2 import IntegrityError


@tagged("post_install", "-at_install")
class TestHeatConfiguration(TransactionCase):
    """Exercise foundation invariants through the ORM and actual access rules."""

    @classmethod
    def setUpClass(cls):
        """Create isolated category and role fixtures."""
        super().setUpClass()
        cls.category = cls.env["heat.consumer.category"].create({"name": "Budget", "code": "TEST"})
        cls.Tariff = cls.env["heat.tariff"]

    def _tariff(self, **values):
        """Create an inclusive tariff with overridable interval and supplier."""
        return self.Tariff.create(
            {
                "category_id": self.category.id,
                "date_from": "2026-10-01",
                "date_to": "2026-10-31",
                "price_per_gcal": 100,
                **values,
            }
        )

    @mute_logger("odoo.sql_db")
    def test_category_unique_code(self):
        """Duplicate codes cannot introduce ambiguous consumer classification."""
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.category.copy({"name": "Duplicate"})

    @mute_logger("odoo.sql_db")
    def test_tariff_price_and_dates(self):
        """Database constraints reject invalid prices and reversed dates."""
        for values in [{"price_per_gcal": 0}, {"price_per_gcal": -1}, {"date_to": "2026-09-30"}]:
            with self.assertRaises(IntegrityError), self.cr.savepoint():
                self._tariff(**values)

    def test_inclusive_overlap_and_adjacent_period(self):
        """The end day is inclusive; the following day starts a valid period."""
        self._tariff()
        with self.assertRaisesRegex(ValidationError, "cannot overlap"), self.cr.savepoint():
            self._tariff(date_from="2026-10-31", date_to=False)
        self._tariff(date_from="2026-11-01", date_to=False)
        with self.assertRaisesRegex(ValidationError, "cannot overlap"), self.cr.savepoint():
            self._tariff(date_from="2027-01-01", date_to=False)

    def test_archive_and_reactivation(self):
        """Archiving preserves links; unarchiving rechecks effective periods."""
        old = self._tariff()
        old.active = False
        self._tariff()
        with self.assertRaisesRegex(ValidationError, "cannot overlap"), self.cr.savepoint():
            old.active = True
        self.category.active = False
        self.assertEqual(old.category_id, self.category)

    def test_tariff_company_isolation(self):
        """Independent suppliers may use identical effective periods."""
        first = self._tariff()
        company = self.env["res.company"].create({"name": "Other Heat Supplier"})
        other = self._tariff(company_id=company.id)
        self.assertNotEqual(first.company_id, other.company_id)

    def test_consumer_requires_category(self):
        """Imports cannot bypass required consumer classification."""
        with self.assertRaisesRegex(ValidationError, "must have a category"), self.cr.savepoint():
            self.env["res.partner"].create({"name": "Consumer", "is_heat_consumer": True})
        with (
            self.assertRaisesRegex(ValidationError, "requires a heat consumer"),
            self.cr.savepoint(),
        ):
            self.env["res.partner"].create({"name": "Contract", "has_heat_contract": True})

    def test_controller_read_only_tariffs(self):
        """A controller reads tariffs but only sales can maintain prices."""
        users = self.env["res.users"]
        controller = users.create(
            {
                "name": "Controller",
                "login": "heat_test_controller",
                "group_ids": [
                    Command.set([self.env.ref("heat_energy_sales.group_heat_controller").id])
                ],
            }
        )
        sales = users.create(
            {
                "name": "Sales",
                "login": "heat_test_sales",
                "group_ids": [Command.set([self.env.ref("heat_energy_sales.group_heat_sales").id])],
            }
        )
        tariff = self._tariff()
        self.assertEqual(tariff.with_user(controller).price_per_gcal, 100)
        with self.assertRaises(AccessError), self.cr.savepoint():
            tariff.with_user(controller).write({"price_per_gcal": 110})
        tariff.with_user(sales).write({"price_per_gcal": 120})
        self.assertEqual(tariff.price_per_gcal, 120)

    def test_company_service_product(self):
        """The configured invoice product must be a service."""
        product = self.env["product.product"].create({"name": "Heat", "type": "consu"})
        with self.assertRaisesRegex(ValidationError, "must be a service"), self.cr.savepoint():
            self.env.company.heat_service_product_id = product
