from odoo import fields, models
from odoo.exceptions import UserError
from odoo.tools import _


class HeatBillGenerateWizard(models.TransientModel):
    """Collect a month and scope, then generate the complete set of heat bills."""

    _name = "heat.bill.generate.wizard"
    _description = "Generate Monthly Heat Bills"
    _check_company_auto = True

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    period_start = fields.Date(
        required=True, default=lambda self: fields.Date.today().replace(day=1)
    )
    node_ids = fields.Many2many(
        "heat.supply.node", check_company=True, domain="[('company_id', '=', company_id)]"
    )
    consumer_ids = fields.Many2many("res.partner", domain="[('is_heat_consumer', '=', True)]")
    replace_draft = fields.Boolean(default=False)

    def action_generate(self):
        """Validate the chosen scope, calculate it and open the resulting bills."""
        self.ensure_one()
        self.check_access("read")
        self.env["heat.bill"]._check_sales()
        if self.node_ids and any(
            not node.active or node.company_id != self.company_id for node in self.node_ids
        ):
            raise UserError(_("Select active nodes belonging to the billing company."))
        nodes = self.node_ids or self.env["heat.supply.node"].search(
            [("company_id", "=", self.company_id.id)]
        )
        if self.consumer_ids:
            nodes = nodes.filtered(
                lambda node: bool(
                    node.object_ids.filtered("active").billing_consumer_id & self.consumer_ids
                )
            )
        if not nodes:
            raise UserError(_("No active supply nodes match the selected consumers."))
        bills = self.env["heat.bill"]._generate(
            self.company_id, self.period_start, nodes=nodes, replace_draft=self.replace_draft
        )
        return bills._result_action()
