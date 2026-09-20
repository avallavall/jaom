# -*- coding: utf-8 -*-
"""Regenerate the i18n ``.pot`` templates for the jaot modules.

Run inside the odoo shell (``odoo shell -d <db>``); each template is written
to ``<module>/i18n/<module>.pot`` so CI can check it in and verify it stays in
sync with the code (SPECS 9.5: "i18n: en + es from day one (.pot checked in
CI)"). The source language is en_US; ``msgstr`` is left empty so a translator
fills in es (or any other locale) against this template.
"""
import io
import os
import odoo.addons.jaot_base as _jb
import odoo.tools.translate as tr

SOURCE_LANG = 'en_US'
MODULES = ['jaot_base', 'jaot_stock', 'jaot_mrp']
# repo root = the parent of the loaded jaot_base package
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(_jb.__file__)))

for module in MODULES:
    buf = io.BytesIO()
    ok = tr.trans_export(SOURCE_LANG, [module], buf, 'po', env)
    if not ok:
        print('no translatable strings for', module)
        continue
    target = os.path.join(ROOT, module, 'i18n', module + '.pot')
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, 'wb') as f:
        f.write(buf.getvalue())
    print('wrote', target, len(buf.getvalue()), 'bytes')
