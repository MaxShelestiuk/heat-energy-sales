from odoo import SUPERUSER_ID, api
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command
from odoo.tests import tagged
from odoo.tools import mute_logger
from psycopg2 import IntegrityError
from psycopg2.errors import LockNotAvailable

from .common_billing import HeatInvoiceCase


@tagged("post_install", "-at_install")
class TestHeatWizardInvoice(HeatInvoiceCase):
    """Exercise batch generation and standard draft invoice integration."""

    def _wizard(self, **values):
        """Scope the wizard to the fixture rather than optional unrelated demo nodes."""
        return self.Wizard.create(
            {"period_start": self.period, "node_ids": [Command.set(self.node.ids)], **values}
        )

    def test_wizard_creates_complete_payers_and_action(self):
        """Filtering to Pharmacy B still preserves the whole shared inlet."""
        wizard = self._wizard(consumer_ids=[Command.set(self.pharmacy_b.ids)])
        action = wizard.action_generate()
        bills = self.Bill.search(action["domain"])
        self.assertEqual(action["res_model"], "heat.bill")
        self.assertEqual(set(bills.consumer_id.ids), {self.hospital.id, self.pharmacy_b.id})
        self.assertEqual(sum(bills.mapped("energy_total_gcal")), 100)
        with self.assertRaisesRegex(UserError, "cannot be replaced"):
            wizard.action_generate()
        self.assertEqual(len(self.Bill.search(action["domain"])), 2)

    def test_wizard_replace_draft_only(self):
        """Replacement is opt-in and cannot affect already calculated documents."""
        draft = self.Bill.create({"consumer_id": self.hospital.id, "period_start": self.period})
        wizard = self._wizard()
        with self.assertRaisesRegex(UserError, "Enable Replace Draft"):
            wizard.action_generate()
        wizard.replace_draft = True
        wizard.action_generate()
        self.assertEqual(draft.state, "calculated")
        with self.assertRaisesRegex(UserError, "cannot be replaced"):
            wizard.action_generate()

    def test_issue_creates_one_draft_with_product_taxes(self):
        """Issuing copies each object line and leaves accounting unposted."""
        bills = self._calculate()
        bill = bills.filtered(lambda row: row.consumer_id == self.hospital)
        bill.action_approve()
        bill.action_issue()
        invoice = bill.account_move_id
        self.assertEqual(bill.state, "issued")
        self.assertEqual(invoice.state, "draft")
        self.assertEqual(invoice.heat_bill_id, bill)
        self.assertEqual(invoice.move_type, "out_invoice")
        self.assertEqual(invoice.partner_id, self.hospital)
        self.assertEqual(len(invoice.invoice_line_ids), 4)
        self.assertEqual(invoice.amount_untaxed, bill.amount_untaxed)
        self.assertEqual(invoice.amount_total, bill.amount_untaxed * 1.2)
        self.assertTrue(all(self.tax in line.tax_ids for line in invoice.invoice_line_ids))
        self.assertEqual(bill.account_move_state, "draft")
        self.assertEqual(invoice.action_open_heat_bill()["res_id"], bill.id)
        self.assertEqual(bill.action_open_account_move()["res_id"], invoice.id)
        with self.assertRaisesRegex(UserError, "approved state"):
            bill.action_issue()
        self.assertEqual(len(bill.account_move_ids), 1)
        with self.assertRaisesRegex(UserError, "cannot be replaced"):
            self._wizard(replace_draft=True).action_generate()
        self.assertEqual(invoice.state, "draft")

    def test_cannot_issue_draft_or_modify_issued_bill(self):
        """Draft-to-issued jumps and edits of historical issued bills fail."""
        bill = self.Bill.create({"consumer_id": self.hospital.id, "period_start": self.period})
        with self.assertRaisesRegex(UserError, "approved state"):
            bill.action_issue()
        bill.action_calculate()
        bill.action_approve()
        bill.action_issue()
        with self.assertRaisesRegex(UserError, "cannot be edited"):
            bill.write({"cancellation_reason": "Forbidden"})
        with self.assertRaisesRegex(UserError, "Only draft, calculated or approved"):
            bill.action_cancel()
        with self.assertRaisesRegex(UserError, "cancelled state"):
            bill.action_reset_draft()
        with self.assertRaisesRegex(UserError, "cannot be deleted"):
            bill.account_move_id.unlink()

    def test_missing_product_is_atomic(self):
        """Missing supplier configuration leaves an approved bill untouched."""
        bill = self._calculate()[:1]
        bill.action_approve()
        self.env.company.heat_service_product_id = False
        with self.assertRaisesRegex(UserError, "Configure an active heat service product"):
            bill.action_issue()
        self.assertEqual(bill.state, "approved")
        self.assertFalse(bill.account_move_id)

    @mute_logger("odoo.sql_db")
    def test_invoice_unique_and_identity_protection(self):
        """Database uniqueness and server checks protect both source directions."""
        bill = self._calculate()[:1]
        bill.action_approve()
        bill.action_issue()
        invoice = bill.account_move_id
        vals = {
            "move_type": "out_invoice",
            "company_id": bill.company_id.id,
            "partner_id": bill.consumer_id.id,
            "journal_id": self.journal.id,
            "heat_bill_id": bill.id,
        }
        with self.assertRaisesRegex(UserError, "Use Issue"):
            self.env["account.move"].create(vals)
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.env["account.move"]._create_heat_invoice(vals)
        with self.assertRaisesRegex(UserError, "cannot be changed"):
            invoice.heat_bill_id = False
        with self.assertRaisesRegex(ValidationError, "must match"), self.cr.savepoint():
            invoice.partner_id = self.pharmacy_a
        with self.assertRaisesRegex(UserError, "workflow buttons"):
            bill.account_move_id = False

    def test_sales_issue_without_general_accounting_write(self):
        """A Sales user can issue an assigned bill without broad accounting ACLs."""
        sales = self._user("heat_invoice_sales", "sales")
        action = (
            self.Wizard.with_user(sales)
            .create({"period_start": self.period, "node_ids": [Command.set(self.node.ids)]})
            .action_generate()
        )
        bill = self.Bill.with_user(sales).search(action["domain"])[:1]
        bill.action_approve()
        bill.action_issue()
        self.assertEqual(bill.state, "issued")
        self.assertEqual(bill.sudo().account_move_id.state, "draft")
        with self.assertRaises(AccessError):
            bill.action_open_account_move()

    def test_wizard_period_and_role_validation(self):
        """Wizard calls cannot bypass period boundaries or the sales role."""
        with self.assertRaisesRegex(UserError, "first day"):
            self._wizard(period_start="2026-10-15").action_generate()
        controller = self._user("heat_wizard_controller", "controller")
        with self.assertRaises(AccessError):
            self.Wizard.with_user(controller).create({"period_start": self.period})

    def test_company_responsible_default(self):
        """Batch-created bills use the supplier's configured responsible user."""
        responsible = self._user("heat_default_responsible", "sales")
        self.env.company.heat_responsible_user_id = responsible
        action = self._wizard().action_generate()
        self.assertEqual(self.Bill.search(action["domain"]).responsible_user_id, responsible)

    @mute_logger("odoo.sql_db")
    def test_competing_transactions_are_serialized(self):
        """A second database transaction cannot enter the same supplier cycle."""
        self.env.company._lock_heat_billing()
        with self.env.registry.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '200ms'")
            other_env = api.Environment(cursor, SUPERUSER_ID, {})
            with self.assertRaises(LockNotAvailable), cursor.savepoint():
                other_env["res.company"].browse(self.env.company.id)._lock_heat_billing()

    def test_context_defaults_cannot_bypass_workflow(self):
        """Default context values are as untrusted as explicit RPC values."""
        with self.assertRaisesRegex(UserError, "draft bill"):
            self.Bill.with_context(default_state="issued").create(
                {"consumer_id": self.hospital.id, "period_start": self.period}
            )
        bill = self.Bill.create({"consumer_id": self.hospital.id, "period_start": self.period})
        with self.assertRaisesRegex(UserError, "Use Issue"):
            self.env["account.move"].with_context(default_heat_bill_id=bill.id).create(
                {"move_type": "out_invoice", "partner_id": self.hospital.id}
            )

    def test_regenerate_cancelled_month(self):
        """Cancelled historical lines release their object/month unique slots."""
        bills = self._calculate()
        bills.cancellation_reason = "Regenerate after source correction"
        bills.action_cancel()
        action = self._wizard().action_generate()
        regenerated = self.Bill.search(action["domain"])
        self.assertFalse(regenerated & bills)
        self.assertEqual(sum(regenerated.mapped("energy_total_gcal")), 100)
        self.assertEqual(set(bills.mapped("state")), {"cancelled"})
        regenerated.action_approve()

    def test_delete_unapproved_source_requires_recalculation(self):
        """Deleting an unapproved observation invalidates its calculated audit."""
        bills = self._calculate()
        reading = bills.source_reading_ids[:1]
        reading.unlink()
        with self.assertRaisesRegex(UserError, "Source readings have changed"):
            bills.action_approve()
