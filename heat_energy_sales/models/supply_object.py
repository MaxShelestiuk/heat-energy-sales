from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import _


class HeatSupplyObject(models.Model):
    """Represent a heated building or room owned by an actual consumer."""

    _name = "heat.supply.object"
    _description = "Heat Supply Object"
    _check_company_auto = True

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    node_id = fields.Many2one(
        "heat.supply.node", required=True, ondelete="restrict", check_company=True
    )
    owner_id = fields.Many2one(
        "res.partner", required=True, ondelete="restrict", check_company=True
    )
    heated_volume_m3 = fields.Float(required=True)
    meter_ids = fields.One2many("heat.meter", "object_id", string="Meter History")
    meter_id = fields.Many2one("heat.meter", compute="_compute_meter", store=True)
    billing_consumer_id = fields.Many2one(
        "res.partner", compute="_compute_billing_consumer", store=True
    )
    company_id = fields.Many2one(related="node_id.company_id", store=True, index=True)
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        "UNIQUE(company_id, code)", "Object code must be unique within a company."
    )
    _positive_volume = models.Constraint(
        "CHECK(heated_volume_m3 > 0)", "Heated volume must be positive."
    )

    @api.depends("meter_ids.active")
    def _compute_meter(self):
        """Expose the object's active submeter from its assignment history."""
        for obj in self:
            obj.meter_id = obj.meter_ids.filtered("active")[:1]

    @api.depends("owner_id", "owner_id.has_heat_contract", "node_id.main_consumer_id")
    def _compute_billing_consumer(self):
        """Choose the payer by contract without changing the owner's tariff category."""
        for obj in self:
            obj.billing_consumer_id = (
                obj.owner_id if obj.owner_id.has_heat_contract else obj.node_id.main_consumer_id
            )

    @api.constrains("owner_id")
    def _check_owner(self):
        """Require every actual owner to be a classified heat consumer."""
        for obj in self:
            if not obj.owner_id.is_heat_consumer or not obj.owner_id.heat_category_id:
                raise ValidationError(
                    _("The object owner must be a heat consumer with a category.")
                )

    def write(self, vals):
        """Do not let an object move away from the node of its installed meters."""
        result = super().write(vals)
        if "node_id" in vals:
            self.sudo().with_context(active_test=False).meter_ids._check_configuration()
        return result

    @api.constrains("meter_id", "billing_consumer_id")
    def _check_derived_assignments(self):
        """Keep imported values from overriding the derived meter or payer."""
        for obj in self:
            if obj.meter_id != obj.meter_ids.filtered("active")[:1]:
                raise ValidationError(_("Assign the object meter from the meter form."))
            expected = (
                obj.owner_id if obj.owner_id.has_heat_contract else obj.node_id.main_consumer_id
            )
            if obj.billing_consumer_id != expected:
                raise ValidationError(
                    _("The billing consumer is determined by the owner's contract.")
                )
