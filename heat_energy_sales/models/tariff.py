from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import _


class HeatTariff(models.Model):
    """Store one category price for an inclusive period and supplier company."""

    _name = "heat.tariff"
    _description = "Heat Tariff"
    _order = "date_from desc, id"
    _check_company_auto = True

    name = fields.Char(compute="_compute_name", store=True)
    category_id = fields.Many2one("heat.consumer.category", required=True, ondelete="restrict")
    date_from = fields.Date(required=True)
    date_to = fields.Date()
    price_per_gcal = fields.Monetary(required=True)
    currency_id = fields.Many2one(
        "res.currency", required=True, default=lambda self: self.env.company.currency_id
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    active = fields.Boolean(default=True)

    _positive_price = models.Constraint(
        "CHECK(price_per_gcal > 0)", "Tariff price must be positive."
    )
    _valid_dates = models.Constraint(
        "CHECK(date_to IS NULL OR date_to >= date_from)",
        "Tariff end date cannot precede its start date.",
    )

    @api.depends("category_id.name", "date_from", "date_to")
    def _compute_name(self):
        """Show the category and full validity period in selection lists."""
        for tariff in self:
            tariff.name = _(
                "%(category)s: %(start)s — %(end)s",
                category=tariff.category_id.name or "",
                start=tariff.date_from or "",
                end=tariff.date_to or _("Open-ended"),
            )

    @api.constrains("category_id", "company_id", "date_from", "date_to", "active")
    def _check_period_overlap(self):
        """Reject two active prices for the same category, company and day."""
        # One batch query also catches overlap introduced by unarchiving several
        # tariffs at once; checking each edited row separately could miss that.
        candidates = self.sudo().search(
            [
                ("company_id", "in", self.company_id.ids),
                ("category_id", "in", self.category_id.ids),
                ("active", "=", True),
            ]
        )
        for tariff in self.filtered("active"):
            for other in candidates:
                if (
                    other.id == tariff.id
                    or other.company_id != tariff.company_id
                    or other.category_id != tariff.category_id
                ):
                    continue
                if (not tariff.date_to or other.date_from <= tariff.date_to) and (
                    not other.date_to or tariff.date_from <= other.date_to
                ):
                    raise ValidationError(
                        _("Active tariff periods cannot overlap for the same category and company.")
                    )
