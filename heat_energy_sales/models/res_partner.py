from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import _


class ResPartner(models.Model):
    """Add heat-consumer, tariff-category and contract details to a partner."""

    _inherit = "res.partner"

    is_heat_consumer = fields.Boolean(string="Heat Consumer")
    heat_category_id = fields.Many2one("heat.consumer.category", ondelete="restrict")
    has_heat_contract = fields.Boolean(string="Active Heat Contract")
    heat_contract_number = fields.Char()
    heat_contract_date = fields.Date()

    @api.constrains("is_heat_consumer", "heat_category_id", "has_heat_contract")
    def _check_heat_consumer(self):
        """Keep heat consumers classified and contracts tied to real consumers."""
        for partner in self:
            if partner.is_heat_consumer and not partner.heat_category_id:
                raise ValidationError(_("A heat consumer must have a category."))
            if partner.has_heat_contract and not partner.is_heat_consumer:
                raise ValidationError(_("A heat contract requires a heat consumer."))

    heat_object_ids = fields.One2many("heat.supply.object", "owner_id")

    def write(self, vals):
        """Recheck linked nodes and objects after contract details change."""
        result = super().write(vals)
        if {"is_heat_consumer", "heat_category_id", "has_heat_contract"} & vals.keys():
            self.env["heat.supply.node"].sudo().with_context(active_test=False).search(
                [("main_consumer_id", "in", self.ids)]
            )._check_main_consumer()
            self.sudo().with_context(active_test=False).heat_object_ids._check_owner()
        return result

    heat_bill_ids = fields.One2many("heat.bill", "consumer_id")
    heat_bill_count = fields.Integer(compute="_compute_heat_bill_count")

    @api.depends("heat_bill_ids")
    def _compute_heat_bill_count(self):
        """Count the payer's heat bills that the current user may see."""
        for partner in self:
            partner.heat_bill_count = len(partner.heat_bill_ids)
