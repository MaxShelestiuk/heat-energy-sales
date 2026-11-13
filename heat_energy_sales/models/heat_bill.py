from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Command
from odoo.tools import _

ENERGY_STEP = Decimal("0.000001")


def energy(value):
    """Round a Gcal value to the six decimal places used by the heat balance."""
    return Decimal(str(value)).quantize(ENERGY_STEP, rounding=ROUND_HALF_UP)


class HeatBill(models.Model):
    """Carry one payer's part of a monthly calculation through its workflow."""

    _name = "heat.bill"
    _description = "Monthly Heat Bill"
    _order = "period_start desc, id desc"
    _check_company_auto = True

    name = fields.Char(required=True, readonly=True, default="New", copy=False)
    consumer_id = fields.Many2one(
        "res.partner", required=True, ondelete="restrict", check_company=True
    )
    period_start = fields.Date(
        required=True, default=lambda self: fields.Date.today().replace(day=1)
    )
    period_end = fields.Date(compute="_compute_period_end", store=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("calculated", "Calculated"),
            ("approved", "Approved"),
            ("issued", "Issued"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="draft",
        readonly=True,
        copy=False,
    )
    line_ids = fields.One2many("heat.bill.line", "bill_id", readonly=True, copy=False)
    energy_total_gcal = fields.Float(compute="_compute_totals", store=True, digits=(16, 6))
    amount_untaxed = fields.Monetary(compute="_compute_totals", store=True)
    currency_id = fields.Many2one(related="company_id.currency_id", store=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    responsible_user_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.company.heat_responsible_user_id or self.env.user,
    )
    calculated_at = fields.Datetime(readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    issued_at = fields.Datetime(readonly=True, copy=False)
    cancellation_reason = fields.Text(copy=False)
    calculation_log = fields.Json(
        readonly=True, copy=False, groups="heat_energy_sales.group_heat_user"
    )
    source_reading_ids = fields.Many2many(
        "heat.meter.reading", readonly=True, copy=False, groups="heat_energy_sales.group_heat_user"
    )

    _monthly_unique = models.UniqueIndex(
        "(consumer_id, company_id, period_start) WHERE state != 'cancelled'",
        "A non-cancelled heat bill already exists for this consumer and month.",
    )
    _month_start = models.Constraint(
        "CHECK(EXTRACT(DAY FROM period_start) = 1)",
        "The billing period must start on the first day of a month.",
    )

    @api.depends("period_start")
    def _compute_period_end(self):
        """Show the month's last day while readings still use exact month boundaries."""
        for bill in self:
            bill.period_end = (
                bill.period_start + relativedelta(months=1, days=-1) if bill.period_start else False
            )

    @api.depends("line_ids.quantity_gcal", "line_ids.subtotal")
    def _compute_totals(self):
        """Add the frozen line quantities and their currency-rounded subtotals."""
        for bill in self:
            bill.energy_total_gcal = sum(bill.line_ids.mapped("quantity_gcal"))
            bill.amount_untaxed = sum(bill.line_ids.mapped("subtotal"))

    @api.model
    def _protected_fields(self):
        """List values that only the calculation and workflow may change."""
        return {
            "name",
            "state",
            "period_end",
            "currency_id",
            "line_ids",
            "energy_total_gcal",
            "amount_untaxed",
            "calculated_at",
            "approved_at",
            "issued_at",
            "calculation_log",
            "source_reading_ids",
            "account_move_id",
            "account_move_ids",
            "account_move_state",
        }

    @api.model_create_multi
    def create(self, vals_list):
        """Create a numbered draft and reject attempts to preload workflow data."""
        self._check_sales()
        if self.env.context.get("default_state", "draft") != "draft" or any(
            self.env.context.get("default_" + field)
            for field in self._protected_fields() - {"state"}
        ):
            raise UserError(_("Create a draft bill and use the workflow buttons."))
        prepared = []
        for vals in vals_list:
            vals = dict(vals)
            if (
                vals.get("state", "draft") != "draft"
                or (self._protected_fields() - {"state"}) & vals.keys()
            ):
                raise UserError(_("Create a draft bill and use the workflow buttons."))
            company = self.env["res.company"].browse(vals.get("company_id") or self.env.company.id)
            if company not in self.env.companies:
                raise AccessError(_("The billing company is not in your allowed companies."))
            vals.setdefault(
                "responsible_user_id", (company.heat_responsible_user_id or self.env.user).id
            )
            vals["state"] = "draft"
            vals["name"] = self.env["ir.sequence"].next_by_code("heat.bill") or _("New")
            prepared.append(vals)
        self.flush_model(["state"])
        return super().create(prepared)

    def write(self, vals):
        """Allow ordinary edits only while the bill is still a draft."""
        self._check_sales()
        self.check_access("write")
        if self._protected_fields() & vals.keys():
            raise UserError(_("Use the workflow buttons to change calculated bill data."))
        if any(b.state in ("issued", "cancelled") for b in self):
            raise UserError(_("Issued or cancelled bills cannot be edited."))
        if set(vals) - {"cancellation_reason"} and any(b.state != "draft" for b in self):
            raise UserError(_("Only draft bill details can be edited."))
        return super().write(vals)

    def unlink(self):
        """Let users delete drafts, but keep every bill that entered the workflow."""
        if self.env.su and self.env.context.get("_force_unlink"):
            return super().unlink()
        self._check_sales()
        if any(b.state != "draft" for b in self):
            raise UserError(_("Only draft bills can be deleted."))
        return super().unlink()

    def _workflow_write(self, vals):
        """Write trusted workflow values without a context key clients could forge."""
        return super().write(vals)

    @api.model
    def _check_sales(self):
        """Require the Heat Sales role before running billing operations."""
        if not self.env.su and not self.env.user.has_group("heat_energy_sales.group_heat_sales"):
            raise AccessError(_("Only Heat Sales users can run the billing workflow."))

    def _require_state(self, expected):
        """Check both write access and the exact state required by a button."""
        self._check_sales()
        self.check_access("write")
        if any(b.state != expected for b in self):
            raise UserError(_("This action requires bills in the %(state)s state.", state=expected))

    @api.model
    def _prepare_calculation(self, nodes, period):
        """Read each inlet once and prepare balanced object lines for the month."""
        if not nodes:
            raise UserError(_("No active supply nodes are available for this calculation."))
        end = period + relativedelta(months=1)
        objects = nodes.object_ids.filtered("active").sorted("id")
        meters = nodes.meter_ids.filtered("active")
        readings = (
            self.env["heat.meter.reading"]
            .sudo()
            .search([("meter_id", "in", meters.ids), ("reading_date", "in", [period, end])])
        )
        # The two boundary dates are fetched for every meter in one query. Apart
        # from avoiding N+1 queries, this gives the whole calculation one source set.
        boundaries = {(r.meter_id.id, r.reading_date): r for r in readings}
        tariffs = self.env["heat.tariff"].search(
            [
                ("company_id", "in", nodes.company_id.ids),
                ("category_id", "in", objects.owner_id.heat_category_id.ids),
                ("date_from", "<=", period),
                "|",
                ("date_to", "=", False),
                ("date_to", ">=", period),
            ]
        )
        prices = defaultdict(list)
        for tariff in tariffs:
            prices[(tariff.company_id.id, tariff.category_id.id)].append(tariff)
        consumption = {}
        for meter in meters:
            start_reading = boundaries.get((meter.id, period))
            end_reading = boundaries.get((meter.id, end))
            if not start_reading or not end_reading:
                raise UserError(
                    _(
                        "Missing exact boundary reading for %(meter)s on %(start)s or %(end)s.",
                        meter=meter.name,
                        start=period,
                        end=end,
                    )
                )
            amount = energy(end_reading.value) - energy(start_reading.value)
            if amount < 0:
                raise UserError(_("Meter consumption cannot be negative."))
            consumption[meter.id] = (amount, start_reading, end_reading)
        planned = []
        audit = []
        for node in nodes.sorted("id"):
            node._check_main_consumer()
            active_objects = objects.filtered(lambda obj, node=node: obj.node_id == node)
            if not node.main_meter_id or not node.main_meter_id.active:
                raise UserError(_("Node %(node)s requires an active main meter.", node=node.name))
            if not active_objects:
                raise UserError(_("Node %(node)s has no active supply objects.", node=node.name))
            sub_meters = node.meter_ids.filtered(lambda m: m.active and m.meter_type == "sub")
            if any(m.object_id not in active_objects for m in sub_meters):
                raise UserError(_("Every active submeter must belong to an active object."))
            main_amount, main_start, main_end = consumption[node.main_meter_id.id]
            residual = main_amount - sum((consumption[m.id][0] for m in sub_meters), Decimal(0))
            if residual < 0:
                raise UserError(_("Main consumption is less than the sum of submeters."))
            unmetered = active_objects.filtered(lambda obj: not obj.meter_id)
            volume = sum((Decimal(str(obj.heated_volume_m3)) for obj in unmetered), Decimal(0))
            if residual > 0 and not volume:
                raise UserError(
                    _("A positive residual requires unmetered objects with heated volume.")
                )
            allocated = Decimal(0)
            node_lines = []
            for obj in active_objects:
                obj._check_owner()
                matches = prices[(node.company_id.id, obj.owner_id.heat_category_id.id)]
                if len(matches) != 1:
                    raise UserError(
                        _(
                            "Exactly one active tariff is required for category %(category)s.",
                            category=obj.owner_id.heat_category_id.name,
                        )
                    )
                tariff = matches[0]
                if tariff.currency_id != node.company_id.currency_id:
                    raise UserError(
                        _("The tariff currency must match the billing company currency.")
                    )
                share = Decimal(0)
                if obj.meter_id:
                    quantity, start_reading, end_reading = consumption[obj.meter_id.id]
                else:
                    share = Decimal(str(obj.heated_volume_m3)) / volume
                    # Rounded shares can leave a few millionths undistributed. The
                    # last object receives exactly what remains, preserving balance.
                    quantity = (
                        residual - allocated
                        if obj == unmetered[-1]
                        else min(energy(residual * share), residual - allocated)
                    )
                    allocated += quantity
                    start_reading, end_reading = main_start, main_end
                if quantity < 0:
                    raise UserError(_("Allocation rounding produced a negative quantity."))
                # Payer and tariff deliberately use different partner facts: the
                # contract chooses who pays, while the owner chooses the category.
                line = {
                    "supply_object_id": obj.id,
                    "node_id": node.id,
                    "actual_consumer_id": obj.owner_id.id,
                    "billing_consumer_id": obj.billing_consumer_id.id,
                    "calculation_method": "meter" if obj.meter_id else "volume",
                    "source_meter_id": (obj.meter_id or node.main_meter_id).id,
                    "start_reading_id": start_reading.id,
                    "end_reading_id": end_reading.id,
                    "heated_volume_m3": obj.heated_volume_m3,
                    "allocation_share": round(float(share), 12),
                    "quantity_gcal": float(quantity),
                    "category_id": obj.owner_id.heat_category_id.id,
                    "tariff_id": tariff.id,
                    "price_unit": tariff.price_per_gcal,
                }
                node_lines.append(line)
            if (
                sum((energy(line["quantity_gcal"]) for line in node_lines), Decimal(0))
                != main_amount
            ):
                raise UserError(_("The node energy balance does not match its main meter."))
            source = readings.filtered(lambda reading, node=node: reading.meter_id.node_id == node)
            audit.append(
                {
                    "node_id": node.id,
                    "main_gcal": float(main_amount),
                    "lines": node_lines,
                    "readings": [
                        {
                            "id": reading.id,
                            "date": str(reading.reading_date),
                            "meter_id": reading.meter_id.id,
                            "value": reading.value,
                        }
                        for reading in source
                    ],
                }
            )
            planned.extend(node_lines)
        return planned, audit, readings

    @api.model
    def _connected_nodes(self, company, nodes=None, consumers=None):
        """Expand a selection until every shared payer and inlet is included."""
        available = self.env["heat.supply.node"].search([("company_id", "=", company.id)])
        selected = nodes or self.env["heat.supply.node"]
        payer_ids = set(consumers.ids if consumers else [])
        # This is a transitive closure, not just one extra search: adding a payer
        # may reveal another node, whose objects may in turn reveal another payer.
        while True:
            payer_ids.update(selected.object_ids.filtered("active").billing_consumer_id.ids)
            expanded = available.filtered(
                lambda node, selected=selected: (
                    node in selected
                    or bool(
                        payer_ids.intersection(
                            node.object_ids.filtered("active").billing_consumer_id.ids
                        )
                    )
                )
            )
            if expanded == selected:
                return selected
            selected = expanded

    @api.model
    def _generate(self, company, period, nodes=None, consumers=None, replace_draft=False):
        """Generate every companion bill for a connected physical calculation."""
        self._check_sales()
        period = fields.Date.to_date(period)
        if not period or period.day != 1:
            raise UserError(_("The billing period must start on the first day of a month."))
        if company not in self.env.companies:
            raise AccessError(_("The billing company is not in your allowed companies."))
        # The company row is the shared lock for readings and calculations. It
        # prevents two transactions from approving different views of the sources.
        company._lock_heat_billing()
        with self.env.cr.savepoint():
            selected = self._connected_nodes(company, nodes, consumers)
            planned, audit, _readings = self._prepare_calculation(selected, period)
            payers = sorted({line["billing_consumer_id"] for line in planned})
            existing = (
                self.sudo()
                .search(
                    [
                        ("company_id", "=", company.id),
                        ("period_start", "=", period),
                        ("consumer_id", "in", payers),
                        ("state", "!=", "cancelled"),
                    ]
                )
                .with_env(self.env)
            )
            existing.check_access("write")
            if any(bill.state != "draft" for bill in existing):
                raise UserError(
                    _(
                        "Existing calculated, approved or issued bills cannot be replaced. Cancel and reset eligible bills first."
                    )
                )
            if existing and not replace_draft:
                raise UserError(
                    _("Draft bills already exist. Enable Replace Draft to calculate them.")
                )
            by_payer = {bill.consumer_id.id: bill for bill in existing}
            new = self.create(
                [
                    {
                        "company_id": company.id,
                        "consumer_id": payer,
                        "period_start": period,
                        "responsible_user_id": (
                            company.heat_responsible_user_id or self.env.user
                        ).id,
                    }
                    for payer in payers
                    if payer not in by_payer
                ]
            )
            by_payer.update({bill.consumer_id.id: bill for bill in new})
            bills = existing | new
            # Lines are replaced only after all sources and existing bills pass.
            # The surrounding savepoint leaves no half-generated payer document.
            bills.line_ids._clear_snapshots()
            self.env["heat.bill.line"]._create_snapshots(
                [dict(line, bill_id=by_payer[line["billing_consumer_id"]].id) for line in planned]
            )
            for bill in bills:
                node_ids = set(bill.line_ids.node_id.ids)
                own_audit = [entry for entry in audit if entry["node_id"] in node_ids]
                source_ids = [
                    entry["id"] for node_audit in own_audit for entry in node_audit["readings"]
                ]
                bill._workflow_write(
                    {
                        "state": "calculated",
                        "calculated_at": fields.Datetime.now(),
                        "calculation_log": own_audit,
                        "source_reading_ids": [Command.set(source_ids)],
                    }
                )
            bills._validate_balance()
            return bills

    def action_calculate(self):
        """Calculate this draft together with every bill sharing its inlets."""
        self.ensure_one()
        self.company_id._lock_heat_billing()
        self._require_state("draft")
        bills = self._generate(
            self.company_id, self.period_start, consumers=self.consumer_id, replace_draft=True
        )
        return bills._result_action()

    def _validate_balance(self):
        """Compare current sources and companion lines with the saved node audit."""
        peers = self.sudo().search(
            [
                ("company_id", "in", self.company_id.ids),
                ("period_start", "in", self.mapped("period_start")),
                ("state", "in", ["calculated", "approved", "issued"]),
            ]
        )
        sources = self.source_reading_ids.sudo()
        by_id = {reading.id: reading for reading in sources}
        for bill in self:
            if not bill.line_ids or not bill.calculation_log:
                raise UserError(
                    _("A bill must have calculated lines and an audit before approval.")
                )
            for node in bill.calculation_log:
                # Approval must fail if a boundary reading changed after Calculate;
                # otherwise the frozen amount would no longer explain its source.
                for snapshot in node["readings"]:
                    reading = by_id.get(snapshot["id"])
                    if (
                        not reading
                        or energy(reading.value) != energy(snapshot["value"])
                        or str(reading.reading_date) != snapshot["date"]
                        or reading.meter_id.id != snapshot["meter_id"]
                    ):
                        raise UserError(
                            _(
                                "Source readings have changed. Cancel and recalculate the affected bills."
                            )
                        )
                # A node can be split across several payers. Validate their lines
                # together so approving one bill cannot hide a missing companion.
                actual = peers.filtered(
                    lambda peer, bill=bill: (
                        peer.company_id == bill.company_id
                        and peer.period_start == bill.period_start
                    )
                ).line_ids.filtered(lambda line, node=node: line.node_id.id == node["node_id"])
                expected = {line["supply_object_id"]: line for line in node["lines"]}
                if len(actual) != len(expected) or set(actual.supply_object_id.ids) != set(
                    expected
                ):
                    raise UserError(
                        _(
                            "The node balance requires all companion bills to remain calculated, approved or issued."
                        )
                    )
                for line in actual:
                    snapshot = expected[line.supply_object_id.id]
                    for key, value in snapshot.items():
                        current = line[key]
                        if key.endswith("_id"):
                            current = current.id
                        if current != value:
                            raise UserError(
                                _("A calculated line no longer matches the node audit.")
                            )
                if sum((energy(line.quantity_gcal) for line in actual), Decimal(0)) != energy(
                    node["main_gcal"]
                ):
                    raise UserError(_("The node energy balance does not match its main meter."))

    def action_approve(self):
        """Approve a calculated bill only while its complete balance is still valid."""
        self.company_id._lock_heat_billing()
        self._require_state("calculated")
        self._validate_balance()
        self._workflow_write({"state": "approved", "approved_at": fields.Datetime.now()})
        return True

    def action_cancel(self):
        """Cancel an unissued bill without breaking an approved companion balance."""
        self._check_sales()
        self.check_access("write")
        self.company_id._lock_heat_billing()
        if any(b.state not in ("draft", "calculated", "approved") for b in self):
            raise UserError(_("Only draft, calculated or approved bills can be cancelled."))
        if (
            any(b.state == "approved" for b in self)
            and not self.env.su
            and not self.env.user.has_group("heat_energy_sales.group_heat_admin")
        ):
            raise AccessError(_("Only a heat administrator can cancel approved bills."))
        if any(not (b.cancellation_reason or "").strip() for b in self):
            raise UserError(_("A cancellation reason is required."))
        protected = self.sudo().search(
            [
                ("company_id", "in", self.company_id.ids),
                ("period_start", "in", self.mapped("period_start")),
                ("state", "in", ["approved", "issued"]),
                ("id", "not in", self.ids),
            ]
        )
        for bill in self:
            if any(
                peer.company_id == bill.company_id
                and peer.period_start == bill.period_start
                and peer.line_ids.node_id & bill.line_ids.node_id
                for peer in protected
            ):
                raise UserError(
                    _("A companion bill is approved or issued; its node balance cannot be broken.")
                )
        self._workflow_write({"state": "cancelled"})
        return True

    def action_reset_draft(self):
        """Turn a cancelled bill into a clean draft when no invoice is attached."""
        self.company_id._lock_heat_billing()
        self._require_state("cancelled")
        if self.account_move_id:
            raise UserError(_("A bill with an accounting invoice cannot return to draft."))
        with self.env.cr.savepoint():
            self.line_ids._clear_snapshots()
            self._workflow_write(
                {
                    "state": "draft",
                    "calculated_at": False,
                    "approved_at": False,
                    "issued_at": False,
                    "calculation_log": False,
                    "source_reading_ids": [Command.clear()],
                    "cancellation_reason": False,
                }
            )
        return True

    def _result_action(self):
        """Open a list containing only the bills returned by the calculation."""
        return {
            "type": "ir.actions.act_window",
            "name": _("Monthly Heat Bills"),
            "res_model": "heat.bill",
            "view_mode": "list,form",
            "domain": [("id", "in", self.ids)],
        }

    account_move_ids = fields.One2many(
        "account.move", "heat_bill_id", string="Accounting Invoices", readonly=True, copy=False
    )
    account_move_id = fields.Many2one(
        "account.move", compute="_compute_account_move", store=True, readonly=True, copy=False
    )
    account_move_state = fields.Selection(
        related="account_move_id.state", string="Accounting Status", readonly=True
    )

    @api.depends("account_move_ids")
    def _compute_account_move(self):
        """Expose the one accounting invoice that points back to this bill."""
        for bill in self:
            bill.account_move_id = bill.account_move_ids[:1]

    def action_issue(self):
        """Issue an approved bill and create its one unposted customer invoice."""
        self.ensure_one()
        self._require_state("approved")
        self.company_id._lock_heat_billing()
        if self.account_move_id:
            raise UserError(_("This heat bill already has an accounting invoice."))
        self._validate_balance()
        company = self.company_id
        product = company.sudo().heat_service_product_id
        if not product or not product.active or product.type != "service":
            raise UserError(
                _("Configure an active heat service product on the company before issuing bills.")
            )
        if product.company_id and product.company_id != company:
            raise UserError(_("The heat service product must belong to the billing company."))
        journal = (
            self.env["account.journal"]
            .sudo()
            .search(
                [("company_id", "=", company.id), ("type", "=", "sale")],
                order="sequence, id",
                limit=1,
            )
        )
        if not journal:
            raise UserError(
                _("Configure a sales journal for the billing company before issuing bills.")
            )
        with self.env.cr.savepoint():
            # Sales may create this specific invoice through the validated workflow;
            # opening or editing it still uses standard accounting access rights.
            move = (
                self.env["account.move"]
                .sudo()
                .with_company(company)
                ._create_heat_invoice(
                    {
                        "move_type": "out_invoice",
                        "company_id": company.id,
                        "journal_id": journal.id,
                        "partner_id": self.consumer_id.id,
                        "currency_id": self.currency_id.id,
                        "invoice_date": self.period_end,
                        "invoice_origin": self.name,
                        "heat_bill_id": self.id,
                        "invoice_line_ids": [
                            Command.create(
                                {
                                    "product_id": product.id,
                                    "name": _(
                                        "%(object)s — %(period)s",
                                        object=line.supply_object_id.name,
                                        period=self.period_start,
                                    ),
                                    "quantity": line.quantity_gcal,
                                    "price_unit": line.price_unit,
                                }
                            )
                            for line in self.line_ids
                        ],
                    }
                )
            )
            if move.state != "draft":
                raise UserError(_("Heat billing must create a draft accounting invoice."))
            self._workflow_write({"state": "issued", "issued_at": fields.Datetime.now()})
        return True

    def action_open_account_move(self):
        """Open the linked invoice without granting extra accounting access."""
        self.ensure_one()
        self.check_access("read")
        self.account_move_id.check_access("read")
        return {
            "type": "ir.actions.act_window",
            "name": _("Accounting Invoice"),
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.account_move_id.id,
        }

    def _get_report_base_filename(self):
        """Use the bill number as the downloaded report's base filename."""
        self.ensure_one()
        return self.name
