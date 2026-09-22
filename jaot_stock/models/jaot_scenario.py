# -*- coding: utf-8 -*-
# License LGPL-3
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class JaotScenario(models.Model):
    _inherit = 'jaot.scenario'

    # The Re-optimize button's visibility is decided client-side, where a
    # many2one's subfields are not reachable in modifier expressions — the
    # recipe check therefore goes through this plain boolean.
    is_vrp = fields.Boolean(
        string='Is routing recipe',
        readonly=True,
        copy=False,
        compute='_compute_is_vrp')

    reoptimize_of_id = fields.Many2one(
        'jaot.scenario',
        string='Re-optimized from',
        copy=False,
        help='The applied routing plan this scenario re-optimizes: the '
             'served legs of that plan stay pinned, the remaining pickings '
             'are re-routed (SPECS 13.4).')
    reoptimize_done = fields.Json(
        string='Pinned served legs',
        copy=False,
        help='Served legs of the frozen plan pinned in this re-route: '
             'a list of {res_id, vehicle, sequence} per done picking.')

    @api.depends('recipe_id.code')
    def _compute_is_vrp(self):
        for sc in self:
            sc.is_vrp = sc.recipe_id.code == 'vrp'

    # -- bridge hooks (SPECS 13.4) ---------------------------------------
    def _extra_solve_options(self):
        if self.reoptimize_of_id:
            return {'pin_done': self.reoptimize_done or []}
        return {}

    def _augment_snapshot(self, snapshot):
        if not self.reoptimize_of_id:
            return snapshot
        # The extraction domain covers confirmed/assigned pickings only;
        # the served (done) legs are injected so the formulation can pin
        # them to their vehicle and position.
        pickings = snapshot.setdefault('stock.picking', {})
        for leg in self.reoptimize_done or []:
            oid = int(leg.get('res_id') or 0)
            if oid in pickings:
                continue
            rec = self.env['stock.picking'].browse(oid)
            if not rec.exists() or rec.state != 'done':
                continue
            partner = rec.partner_id
            pickings[oid] = {
                'order_lat': partner.partner_latitude,
                'order_lng': partner.partner_longitude,
                'order_demand': rec.shipping_weight,
                'current_vehicle': leg.get('vehicle'),
                'current_sequence': leg.get('sequence'),
            }
        return snapshot

    def action_reoptimize(self):
        """applied -> child: re-route the remaining pickings with the served
        legs pinned (SPECS 13.4). A new scenario of the same recipe carries
        the done legs of the frozen plan and is submitted; once solved, its
        KPI delta against the frozen plan and the per-line diff are stored
        on it (the baseline machinery)."""
        self.ensure_one()
        self._check_modify_access()
        if self.state != 'applied':
            raise UserError(_("Only an applied scenario can be "
                              "re-optimized."))
        if self.recipe_id.code != 'vrp':
            raise UserError(_("Re-optimization is only available for the "
                              "routing (vrp) recipe."))
        if not self.data_stale:
            raise UserError(_("The source data is not stale: run the "
                              "staleness check before re-optimizing."))
        done_legs = []
        for line in self.scenario_line_ids:
            if line.res_model != 'stock.picking':
                continue
            rec = self.env['stock.picking'].browse(line.res_id)
            if not rec.exists() or rec.state != 'done':
                continue
            decision = line.decision or {}
            vehicle = decision.get('jaot_vehicle_id')
            sequence = decision.get('jaot_route_sequence')
            if not vehicle or not sequence:
                continue
            done_legs.append({
                'res_id': int(line.res_id),
                'vehicle': int(vehicle),
                'sequence': int(sequence),
            })
        if not done_legs:
            raise UserError(_("No served legs to pin: none of the plan's "
                              "pickings is done yet."))
        child = self.create({
            'name': f'{self.name} (re-optimize)',
            'recipe_id': self.recipe_id.id,
            'company_id': self.company_id.id,
            'reoptimize_of_id': self.id,
            'reoptimize_done': done_legs,
        })
        child.action_submit()
        return child

    def _finalize_from_execution(self, config):
        super()._finalize_from_execution(config)
        parent = self.reoptimize_of_id
        if parent and self.state == 'solved':
            self._store_reoptimize_delta(parent)

    def _store_reoptimize_delta(self, parent):
        """Write the re-route-vs-frozen-plan KPI delta onto this (re-route)
        scenario: the frozen applied plan is the reference, like the
        baseline of a comparison."""
        parent.ensure_one()
        frozen = parent.objective_value
        optimized = self.objective_value
        sense = parent.objective_sense
        if frozen is not None and optimized is not None:
            delta = (frozen - optimized if sense != 'maximize'
                     else optimized - frozen)
        else:
            delta = None
        summary = dict(self.kpi_summary or {})
        summary.update({
            'baseline_objective': frozen,
            'optimized_objective': optimized,
            'delta_vs_baseline': delta,
            'sense': sense,
        })
        self.kpi_summary = summary
        self._write_line_deltas(parent)
