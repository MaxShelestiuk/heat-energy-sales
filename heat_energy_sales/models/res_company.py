from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import _


class ResCompany(models.Model):
    """Hold the supplier settings reused by heat bills, invoices and reports."""

    _inherit = "res.company"

    heat_responsible_user_id = fields.Many2one("res.users", string="Heat Billing Responsible")
    heat_service_product_id = fields.Many2one(
        "product.product",
        string="Heat Service Product",
        domain="[('type', '=', 'service')]",
        check_company=True,
    )
    heat_report_footer = fields.Text(string="Heat Report Footer")

    @api.constrains("heat_service_product_id")
    def _check_heat_service_product(self):
        """Accept only a service product for future heat invoice lines."""
        for company in self:
            if (
                company.heat_service_product_id
                and company.heat_service_product_id.type != "service"
            ):
                raise ValidationError(_("The heat billing product must be a service."))

    def _lock_heat_billing(self):
        """Make concurrent reading edits and bill calculations run one after another.

        Updating the company row to the same value is intentional. Under
        PostgreSQL's REPEATABLE READ isolation it invalidates an older concurrent
        snapshot, and Odoo retries that transaction with fresh readings. Callers
        reach this helper only after their normal access checks have passed.
        """
        if self:
            self.flush_recordset(["write_date"])
            self.env.cr.execute(
                "UPDATE res_company SET write_date = write_date WHERE id IN %s",
                [tuple(sorted(self.ids))],
            )
