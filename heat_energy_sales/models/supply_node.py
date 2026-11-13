from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import _


class HeatSupplyNode(models.Model):
    """Group the objects supplied through one physical heat inlet."""

    _name = "heat.supply.node"
    _description = "Heat Supply Node"
    _check_company_auto = True

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    main_consumer_id = fields.Many2one(
        "res.partner", required=True, ondelete="restrict", check_company=True
    )
    meter_ids = fields.One2many("heat.meter", "node_id")
    main_meter_id = fields.Many2one("heat.meter", compute="_compute_main_meter", store=True)
    object_ids = fields.One2many("heat.supply.object", "node_id")
    responsible_user_id = fields.Many2one("res.users", default=lambda self: self.env.user)
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        "UNIQUE(company_id, code)", "Node code must be unique within a company."
    )

    @api.depends("meter_ids.active", "meter_ids.meter_type")
    def _compute_main_meter(self):
        """Expose the node's one active main meter from its meter records."""
        for node in self:
            node.main_meter_id = node.meter_ids.filtered(
                lambda m: m.active and m.meter_type == "main"
            )[:1]

    @api.constrains("main_consumer_id")
    def _check_main_consumer(self):
        """Require a valid contracted payer for owners without contracts."""
        for node in self:
            partner = node.main_consumer_id
            if (
                not partner.is_heat_consumer
                or not partner.heat_category_id
                or not partner.has_heat_contract
            ):
                raise ValidationError(
                    _("The main consumer must have a heat category and an active heat contract.")
                )

    def write(self, vals):
        """Recheck attached meters and objects if the node changes company."""
        result = super().write(vals)
        if "company_id" in vals:
            self.sudo().with_context(active_test=False).meter_ids._check_configuration()
            self.sudo().with_context(active_test=False).object_ids._check_company()
        return result

    @api.constrains("main_meter_id")
    def _check_derived_meter(self):
        """Reject attempts to set the derived main-meter field directly."""
        for node in self:
            expected = node.meter_ids.filtered(lambda m: m.active and m.meter_type == "main")[:1]
            if node.main_meter_id != expected:
                raise ValidationError(_("Assign the main meter from the meter form."))
