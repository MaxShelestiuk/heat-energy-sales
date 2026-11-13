import itertools

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import _
from odoo.tools.sql import SQL


class HeatMeterReading(models.Model):
    """Store a meter's cumulative value on the date it was actually read."""

    _name = "heat.meter.reading"
    _description = "Heat Meter Reading"
    _order = "reading_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(compute="_compute_name", store=True)
    # company_id is derived from this field.  Enabling check_company here would
    # build a circular client domain: before a meter is selected, company_id is
    # empty, so Odoo would offer only company-less meters in the selector.
    meter_id = fields.Many2one("heat.meter", required=True, index=True, ondelete="restrict")
    node_id = fields.Many2one(related="meter_id.node_id", store=True, index=True)
    object_id = fields.Many2one(related="meter_id.object_id", store=True, index=True)
    reading_date = fields.Date(required=True, index=True, default=fields.Date.context_today)
    value = fields.Float(required=True, digits=(16, 6))
    consumption_delta = fields.Float(
        string="Consumption Delta",
        compute="_compute_consumption_delta",
        digits=(16, 6),
        aggregator="sum",
        help=(
            "On a reading, this is the difference from the previous visible reading. "
            "In a grouped list, it is the latest selected value minus the earliest "
            "selected value for each meter."
        ),
    )
    controller_user_id = fields.Many2one("res.users", required=True)
    note = fields.Text()
    company_id = fields.Many2one(related="meter_id.company_id", store=True, index=True)
    is_boundary_reading = fields.Boolean(compute="_compute_boundary")

    _date_unique = models.Constraint(
        "UNIQUE(meter_id, reading_date)", "Only one reading per meter and date is allowed."
    )
    _nonnegative = models.Constraint(
        "CHECK(value >= 0)", "A cumulative reading cannot be negative."
    )

    @api.depends("meter_id.name", "reading_date")
    def _compute_name(self):
        """Give each reading a short meter-and-date label."""
        for reading in self:
            reading.name = f"{reading.meter_id.name or ''}: {reading.reading_date or ''}"

    @api.depends("reading_date")
    def _compute_boundary(self):
        """Mark readings taken on the first day of a month."""
        for reading in self:
            reading.is_boundary_reading = bool(
                reading.reading_date and reading.reading_date.day == 1
            )

    @api.depends("meter_id", "reading_date", "value")
    def _compute_consumption_delta(self):
        """Show how much the meter increased since its previous reading."""
        values = {reading.id: 0.0 for reading in self}
        dated = self.filtered(lambda reading: reading.meter_id and reading.reading_date)
        if dated:
            timeline = self.search(
                [
                    ("meter_id", "in", dated.meter_id.ids),
                    ("reading_date", "<=", max(dated.mapped("reading_date"))),
                ],
                order="meter_id, reading_date, id",
            )
            previous = {}
            selected_ids = set(dated.ids)
            for reading in timeline:
                if reading.id in selected_ids and reading.meter_id.id in previous:
                    values[reading.id] = reading.value - previous[reading.meter_id.id]
                previous[reading.meter_id.id] = reading.value
        for reading in self:
            reading.consumption_delta = values[reading.id]

    def _read_group_select(self, aggregate_spec, query):
        """Leave grouped consumption blank in SQL so Python can compute a true delta."""
        if aggregate_spec == "consumption_delta:sum":
            return SQL("NULL")
        return super()._read_group_select(aggregate_spec, query)

    @api.model
    def _read_group(
        self,
        domain,
        groupby=(),
        aggregates=(),
        having=(),
        offset=0,
        limit=None,
        order=None,
    ):
        """Report grouped consumption as the last value minus the first per meter."""
        aggregate = "consumption_delta:sum"
        if aggregate not in aggregates:
            return super()._read_group(
                domain, groupby, aggregates, having, offset, limit, order
            )
        base_aggregates = [item for item in aggregates if item != aggregate]
        base_aggregates.append("id:recordset")
        rows = super()._read_group(
            domain, groupby, base_aggregates, having, offset, limit, order
        )
        result = []
        for *values, records in rows:
            deltas = 0.0
            # Summing cumulative readings would exaggerate consumption. Each
            # meter contributes only its change across the selected interval.
            for meter in records.meter_id:
                readings = records.filtered(lambda reading, meter=meter: reading.meter_id == meter)
                readings = readings.sorted(lambda reading: (reading.reading_date, reading.id))
                if len(readings) > 1:
                    deltas += readings[-1].value - readings[0].value
            for index, spec in enumerate(itertools.chain(groupby, aggregates)):
                if spec == aggregate:
                    values.insert(index, deltas)
            result.append(tuple(values))
        return result

    @api.onchange("meter_id")
    def _onchange_meter(self):
        """Prefill the controller when a user picks a meter in the form."""
        self.controller_user_id = self.meter_id.controller_user_id

    @api.model_create_multi
    def create(self, vals_list):
        """Apply the meter's controller for imports as well as form entries."""
        meters = self.env["heat.meter"].browse(
            [v["meter_id"] for v in vals_list if v.get("meter_id")]
        )
        self.check_access("create")
        meters.company_id._lock_heat_billing()
        controllers = {m.id: m.controller_user_id.id for m in meters}
        vals_list = [
            dict(
                v,
                controller_user_id=v.get("controller_user_id")
                or controllers.get(v.get("meter_id")),
            )
            for v in vals_list
        ]
        for vals in vals_list:
            self._check_controller_values(vals)
        return super().create(vals_list)

    def _check_controller_values(self, vals):
        """Stop controllers from writing readings for somebody else's meter."""
        if self.env.su or self.env.user.has_group("heat_energy_sales.group_heat_admin"):
            return
        if vals.get("controller_user_id", self.env.uid) != self.env.uid:
            raise AccessError(_("You can only record readings for your own assigned meters."))
        if vals.get("meter_id"):
            meter = self.env["heat.meter"].browse(vals["meter_id"])
            meter.check_access("read")
            if meter.controller_user_id != self.env.user:
                raise AccessError(_("You can only record readings for your own assigned meters."))

    def write(self, vals):
        """Protect billed sources and controller ownership before an edit."""
        self.check_access("write")
        companies = self.company_id
        if vals.get("meter_id"):
            target = self.env["heat.meter"].browse(vals["meter_id"])
            target.check_access("read")
            companies |= target.company_id
        companies._lock_heat_billing()
        self._check_billing_lock()
        self._check_controller_values(vals)
        return super().write(vals)

    @api.constrains("meter_id", "reading_date", "value")
    def _check_readings(self):
        """Check the whole meter timeline, not only the records visible to one user."""
        readings = self.sudo().search(
            [("meter_id", "in", self.meter_id.ids)], order="meter_id, reading_date, id"
        )
        previous = {}
        for reading in readings:
            if reading.reading_date < reading.meter_id.installation_date:
                raise ValidationError(_("A reading cannot precede the meter installation date."))
            if reading.meter_id.id in previous and reading.value < previous[reading.meter_id.id]:
                raise ValidationError(_("Cumulative readings cannot decrease between dates."))
            previous[reading.meter_id.id] = reading.value

    def _check_billing_lock(self):
        """Freeze a reading after an approved or issued bill starts relying on it."""
        if (
            self.env["heat.bill"]
            .sudo()
            .search_count(
                [("source_reading_ids", "in", self.ids), ("state", "in", ["approved", "issued"])],
                limit=1,
            )
        ):
            raise ValidationError(
                _("Readings used by approved or issued bills cannot be changed or deleted.")
            )

    def unlink(self):
        """Apply the same billing checks to deletion as to an ordinary edit."""
        if self.env.su and self.env.context.get("_force_unlink"):
            return super().unlink()
        self.check_access("unlink")
        self.company_id._lock_heat_billing()
        self._check_billing_lock()
        return super().unlink()
