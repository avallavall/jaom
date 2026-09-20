"""Restricted expression evaluation for jaot.binding (SPECS 5.4, 7.3).

Bindings may carry a ``domain`` (an Odoo domain literal) and an
``expression`` (a small arithmetic/lookup expression over record values).
Both are evaluated with a closed namespace: only whitelisted builtins are
reachable and everything else ``safe_eval`` refuses at the AST level.
Every evaluation is logged (SPECS 5.4: "every evaluation logged").
"""

import ast
import logging

from odoo import _
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

_EXPR_NAMES = {
    'abs': abs,
    'all': all,
    'any': any,
    'float': float,
    'int': int,
    'len': len,
    'max': max,
    'min': min,
    'round': round,
    'sum': sum,
}


def validate_expression(expression):
    """Raise UserError if ``expression`` is not syntactically valid.

    Node-level restrictions are enforced at evaluation time by
    ``safe_eval`` itself.
    """
    if not expression:
        return
    try:
        ast.parse(expression, mode='eval')
    except SyntaxError as exc:
        raise UserError(_(
            'Invalid expression "%s": %s', expression, exc.msg)) from exc


def validate_domain(domain):
    """Raise UserError if ``domain`` is not a valid Odoo domain literal.

    A valid literal is a list of conditions; anything else (e.g. the
    bare literal ``5``) parses fine but is not a domain and would crash
    the extraction, so it is rejected at authoring time.
    """
    if not domain:
        return
    try:
        value = safe_eval(domain, {})
    except Exception as exc:
        raise UserError(_(
            'Invalid domain "%s": %s', domain, exc)) from exc
    if not isinstance(value, list):
        raise UserError(_(
            'Invalid domain "%s": must be a list of conditions.', domain))


def evaluate(expression, values, context=''):
    """Evaluate ``expression`` against ``values`` with the closed namespace.

    ``values`` maps the record field names referenced by the expression to
    their values. Logs every evaluation (SPECS 5.4).
    """
    _logger.info('JAOT expression evaluation (%s): %s', context, expression)
    try:
        return safe_eval(expression, dict(values, **_EXPR_NAMES))
    except Exception as exc:
        raise UserError(_(
            'JAOT expression "%s" failed to evaluate: %s',
            expression, exc)) from exc


def evaluate_domain(domain, context=''):
    """Parse a stored domain literal back into a Python domain."""
    if not domain:
        return []
    _logger.info('JAOT domain evaluation (%s): %s', context, domain)
    return safe_eval(domain, {})
