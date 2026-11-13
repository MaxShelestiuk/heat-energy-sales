from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import _


class AccountMove(models.Model):
    """Link a standard customer invoice to the heat bill it came from."""

    _inherit = "account.move"

    heat_bill_id = fields.Many2one(
        "heat.bill", readonly=True, copy=False, ondelete="restrict", check_company=True, index=True
    )
    _heat_bill_unique = models.Constraint(
        "UNIQUE(heat_bill_id)", "Only one accounting invoice may reference a heat bill."
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Stop users and imports from attaching an invoice to a bill by hand."""
        if self.env.context.get("default_heat_bill_id") or any(
            vals.get("heat_bill_id") for vals in vals_list
        ):
            raise UserError(_("Use Issue on the heat bill to create its accounting invoice."))
        return super().create(vals_list)

    @api.model
    def _create_heat_invoice(self, vals):
        """Create the invoice after the heat-billing workflow has checked it."""
        return super().create(vals)

    @api.constrains("heat_bill_id", "company_id", "partner_id", "move_type", "currency_id")
    def _check_heat_origin(self):
        """Make sure the invoice still describes its approved source bill."""
        for move in self.filtered("heat_bill_id"):
            bill = move.heat_bill_id
            if (
                move.company_id != bill.company_id
                or move.partner_id != bill.consumer_id
                or move.currency_id != bill.currency_id
                or move.move_type != "out_invoice"
                or bill.state not in ("approved", "issued")
            ):
                raise ValidationError(
                    _(
                        "The invoice must match its approved heat bill's company, consumer and currency."
                    )
                )

    def write(self, vals):
        """Keep the source link fixed and leave other edits to standard accounting."""
        if "heat_bill_id" in vals:
            raise UserError(_("The originating heat bill link cannot be changed."))
        return super().write(vals)

    def unlink(self):
        """Keep invoices that form part of an issued bill's audit trail."""
        if self.env.su and self.env.context.get("_force_unlink"):
            return super().unlink()
        if self.filtered("heat_bill_id"):
            raise UserError(_("An invoice linked to a heat bill cannot be deleted."))
        return super().unlink()

    def action_open_heat_bill(self):
        """Open the source heat bill after checking the user's normal access."""
        self.ensure_one()
        self.check_access("read")
        self.heat_bill_id.check_access("read")
        return {
            "type": "ir.actions.act_window",
            "name": _("Heat Bill"),
            "res_model": "heat.bill",
            "view_mode": "form",
            "res_id": self.heat_bill_id.id,
        }
