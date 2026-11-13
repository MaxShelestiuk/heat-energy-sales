from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import _


class HeatMeter(models.Model):
    """Represent a physical meter and the node or object where it is installed."""

    _name = "heat.meter"
    _description = "Heat Meter"
    _check_company_auto = True

    name = fields.Char(required=True)
    serial_number = fields.Char(required=True)
    meter_type = fields.Selection(
        [("main", "Main"), ("sub", "Submeter")], required=True, default="main"
    )
    node_id = fields.Many2one(
        "heat.supply.node", required=True, ondelete="restrict", check_company=True
    )
    object_id = fields.Many2one(
        "heat.supply.object",
        ondelete="restrict",
        check_company=True,
        domain="[('node_id', '=', node_id)]",
    )
    controller_user_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user
    )
    installation_date = fields.Date(required=True, default=fields.Date.context_today)
    unit = fields.Selection([("gcal", "Gcal")], required=True, default="gcal")
    reading_ids = fields.One2many("heat.meter.reading", "meter_id")
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    active = fields.Boolean(default=True)

    _serial_unique = models.Constraint(
        "UNIQUE(company_id, serial_number)", "Meter serial number must be unique within a company."
    )
    _type_object = models.Constraint(
        "CHECK((meter_type = 'main' AND object_id IS NULL) OR (meter_type = 'sub' AND object_id IS NOT NULL))",
        "A main meter has no object; a submeter requires an object.",
    )
    _main_active_unique = models.UniqueIndex(
        "(node_id) WHERE active AND meter_type = 'main'",
        "A node can have only one active main meter.",
    )
    _sub_active_unique = models.UniqueIndex(
        "(object_id) WHERE active AND meter_type = 'sub'",
        "An object can have only one active submeter.",
    )

    @api.constrains("node_id", "object_id", "company_id")
    def _check_configuration(self):
        """Keep a meter, its node and its object inside the same topology."""
        for meter in self:
            if meter.company_id != meter.node_id.company_id:
                raise ValidationError(_("Meter and node must belong to the same company."))
            if meter.object_id and meter.object_id.node_id != meter.node_id:
                raise ValidationError(_("Meter and object must belong to the same node."))

    @api.model_create_multi
    def create(self, vals_list):
        """Create meters without bypassing controller or active-meter rules."""
        # PostgreSQL must see pending archive changes before it checks the partial
        # unique indexes for the new main meter or submeter.
        self.flush_model(["active", "node_id", "object_id", "meter_type"])
        if not self.env.su and not self.env.user.has_group("heat_energy_sales.group_heat_admin"):
            for vals in vals_list:
                if vals.get("controller_user_id", self.env.uid) != self.env.uid:
                    raise AccessError(
                        _("Only a heat administrator can assign a different controller.")
                    )
        return super().create(vals_list)

    def write(self, vals):
        """Preserve reading history and limit who may reassign a controller."""
        if (
            "controller_user_id" in vals
            and not self.env.su
            and not self.env.user.has_group("heat_energy_sales.group_heat_admin")
            and vals["controller_user_id"] != self.env.uid
        ):
            raise AccessError(_("Only a heat administrator can assign a different controller."))
        if {
            "node_id",
            "object_id",
            "meter_type",
            "company_id",
        } & vals.keys() and self.sudo().reading_ids:
            raise ValidationError(
                _("A meter with readings cannot change its node, object, type or company.")
            )
        result = super().write(vals)
        if "installation_date" in vals:
            self.sudo().reading_ids._check_readings()
        return result
