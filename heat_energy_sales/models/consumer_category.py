from odoo import fields, models


class HeatConsumerCategory(models.Model):
    """Describe a consumer group whose code and tariffs remain stable over time."""

    _name = "heat.consumer.category"
    _description = "Heat Consumer Category"
    _order = "name, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    description = fields.Text()
    active = fields.Boolean(default=True)
    tariff_ids = fields.One2many("heat.tariff", "category_id")

    _code_unique = models.Constraint("UNIQUE(code)", "Category code must be unique.")
