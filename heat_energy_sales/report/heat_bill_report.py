from odoo import api, models


class HeatBillReport(models.AbstractModel):
    """Render heat bills without letting the report route bypass record access."""

    _name = "report.heat_energy_sales.report_heat_bill"
    _description = "Heat Energy Bill Report"

    @api.model
    def _get_report_values(self, docids, data=None):
        """Check every requested bill before reading related report details."""
        bills = self.env["heat.bill"].browse(docids)
        bills.check_access("read")
        return {"doc_ids": bills.ids, "doc_model": "heat.bill", "docs": bills.sudo()}
