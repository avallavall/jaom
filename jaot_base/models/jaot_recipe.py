from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..jaot_expr import validate_domain, validate_expression


class JaotRecipe(models.Model):
    _name = 'jaot.recipe'
    _description = 'JAOT recipe'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    domain = fields.Selection([
        ('stock', 'Stock'),
        ('mrp', 'MRP'),
        ('hr', 'HR'),
        ('purchase', 'Purchase'),
        ('account', 'Accounting'),
    ], required=True, default='stock')
    jaot_template_id = fields.Char(
        string='JAOT template',
        help='JAOT template slug or id this recipe maps to.')
    description = fields.Text()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    recipe_role_ids = fields.One2many('jaot.recipe.role', 'recipe_id')
    binding_ids = fields.One2many('jaot.binding', 'recipe_id')

    _code_company_uniq = models.Constraint(
        'UNIQUE (code, company_id)',
        'A recipe code must be unique per company.',
    )

    def action_validate(self):
        """Syntax-check every binding's domain and expression (SPECS 5.4)."""
        self.ensure_one()
        for binding in self.binding_ids:
            # expression is group_system-gated for UI exposure; the
            # manager-gated Validate button must still be able to check it.
            privileged = binding.sudo()
            if privileged.domain:
                validate_domain(privileged.domain)
            if privileged.expression:
                validate_expression(privileged.expression)
        return {
            'type': 'ir.actions.client',
            'params': {
                'title': 'JAOT',
                'name': 'display_notification',
                'params': {
                    'title': 'JAOT',
                    'message': 'Recipe validated: no syntax errors.',
                    'type': 'success',
                },
            },
        }

    def action_show_bindings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Bindings',
            'res_model': 'jaot.binding',
            'view_mode': 'list,form',
            'domain': [('recipe_id', '=', self.id)],
            'context': {'default_recipe_id': self.id},
        }


class JaotRecipeRole(models.Model):
    _name = 'jaot.recipe.role'
    _description = 'JAOT recipe role'
    _rec_name = 'name'

    recipe_id = fields.Many2one(
        'jaot.recipe', required=True, ondelete='cascade')
    name = fields.Char(required=True)
    kind = fields.Selection([
        ('variable', 'Variable'),
        ('constraint', 'Constraint'),
        ('parameter', 'Parameter'),
    ], required=True, default='variable')
    required = fields.Boolean(string='Required', default=True)
    semantics = fields.Text(help='Human-readable meaning of this role.')
    data_type = fields.Selection([
        ('number', 'Number'),
        ('quantity', 'Quantity'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
        ('reference', 'Reference'),
    ], default='number')


class JaotBinding(models.Model):
    _name = 'jaot.binding'
    _description = 'JAOT binding'
    _rec_name = 'display_name'

    display_name = fields.Char(compute='_compute_display_name')
    recipe_id = fields.Many2one(
        'jaot.recipe', required=True, ondelete='cascade')
    role_id = fields.Many2one(
        'jaot.recipe.role', required=True, ondelete='cascade')
    res_model = fields.Char(
        string='Source model',
        help='Odoo model the role is extracted from, e.g. stock.picking. '
             'Required for variable/constraint roles; omitted for parameter '
             'roles (which carry a constant_value).')
    field_path = fields.Char(
        help='Dotted path to the value, e.g. production_id.date_deadline.')
    domain = fields.Char(
        help='Optional evaluable Odoo domain restricting the records used.')
    expression = fields.Char(
        groups='base.group_system',
        help='Optional restricted expression evaluated over the record '
             'values. Only a closed namespace is available (SPECS 5.4). '
             'Visible to administrators only.')
    constant_value = fields.Char(
        string='Constant value',
        help='For parameter roles: a literal number (no Odoo source). '
             'Ignored for variable/constraint roles, which use '
             'res_model + field_path.')
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)

    _role_company_uniq = models.Constraint(
        'UNIQUE (role_id, company_id)',
        'Only one binding per role per company.',
    )

    @api.depends('recipe_id', 'role_id')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = (
                f"{rec.recipe_id.code or '?'} / {rec.role_id.name or '?'}")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._validate(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._validate(vals)
        return super().write(vals)

    def _validate(self, vals):
        if vals.get('expression'):
            validate_expression(vals['expression'])
        if vals.get('domain'):
            validate_domain(vals['domain'])
        self._validate_source(vals)

    def _validate_source(self, vals):
        """A parameter role carries a constant_value; every other role
        needs a source model (field_path is optional for pure reference
        roles that only define the record set)."""
        role_id = vals.get('role_id')
        if role_id is not None:
            role = self.env['jaot.recipe.role'].browse(int(role_id)).exists()
        else:
            role = self.role_id
        if not role:
            return
        if role.kind == 'parameter':
            const = vals.get('constant_value')
            if const is None and self and self.id:
                const = self.constant_value
            if not const:
                raise UserError(_(
                    "Parameter role '%(r)s' needs a constant value.",
                    r=role.name))
            # Extraction does float() on the constant, so a non-numeric
            # value would crash scenario submission (SPECS 5.4: validate
            # at authoring, not at solve time).
            try:
                float(const)
            except (TypeError, ValueError):
                raise UserError(_(
                    "Parameter role '%(r)s' constant '%(c)s' is not a "
                    "number.", r=role.name, c=const))
        else:
            res_model = vals.get('res_model')
            if res_model is None and self and self.id:
                res_model = self.res_model
            if not res_model:
                raise UserError(_(
                    "Role '%(r)s' needs a source model (res_model).",
                    r=role.name))
