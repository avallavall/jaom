# -*- coding: utf-8 -*-
# Load the Spanish (es_ES) translations for the e2e database, with the
# committed .po files as the source of truth for the JAOT modules. Piped
# into an odoo shell:
#
#   docker compose -f dev/docker-compose.yml run --rm odoo \
#       odoo shell -d e2e --no-http < dev/e2e/load_es.py
#
# The language must exist and be active in res.lang before any catalog can
# be loaded, so it is created first when missing. The one update call
# below then (re)loads every installed module's es catalog with
# overwrite=True — including base-module Spanish and the three JAOT
# catalogs from the committed es.po files.

lang = env['res.lang'].with_context(active_test=False).search(
    [('code', '=', 'es_ES')], limit=1)
if not lang:
    lang = env['res.lang']._create_lang('es_ES')
if not lang.active:
    lang.active = True
env['ir.module.module'].search([('state', '=', 'installed')]).\
    _update_translations(['es_ES'], overwrite=True)
env.cr.commit()
print('jaot es catalogs loaded')
