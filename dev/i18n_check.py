"""Verify the committed .pot templates match the freshly regenerated ones.

The i18n CI job regenerates the templates into the checkout
(``dev/gen_i18n.py``) and this script compares each regenerated file
against the committed version (HEAD). The two header lines Odoo
re-stamps on every export (``POT-Creation-Date`` / ``PO-Revision-Date``)
are ignored — a fresh export always carries a new date, so a raw
byte-diff would fail on every run. Any other difference means the
committed templates are stale: the i18n job goes red (SPECS §10.5).

Stdlib only, runs on the CI host and locally (no Odoo needed).
"""
import difflib
import pathlib
import re
import subprocess
import sys

# In a .pot the header lives inside a quoted multi-line msgstr, so the
# stamp lines look like: "POT-Creation-Date: 2026-09-19 21:31+0000\n"
STAMP_RE = re.compile(r'^"\s*(POT-Creation-Date|PO-Revision-Date):')


def normalize(text):
    return '\n'.join(
        line for line in text.splitlines() if not STAMP_RE.match(line))


def main():
    pots = sorted(pathlib.Path('.').glob('*/i18n/*.pot'))
    if not pots:
        print('no .pot templates found — nothing to check', file=sys.stderr)
        return 1
    failed = False
    for pot in pots:
        fresh = pot.read_text(encoding='utf-8')
        # A template with no committed version yet is new in this commit
        # cycle: nothing to drift from, so report it and move on.
        try:
            head = subprocess.run(
                ['git', 'show', f'HEAD:{pot.as_posix()}'],
                capture_output=True, check=True).stdout.decode('utf-8')
        except subprocess.CalledProcessError:
            print(f'NEW  {pot.as_posix()} (not in HEAD yet)')
            continue
        if normalize(head) == normalize(fresh):
            print(f'OK   {pot.as_posix()}')
            continue
        failed = True
        print(f'STALE {pot.as_posix()} (differs from HEAD beyond the stamps):')
        diff = difflib.unified_diff(
            normalize(head).splitlines(),
            normalize(fresh).splitlines(),
            fromfile=f'HEAD:{pot.as_posix()}',
            tofile=f'working:{pot.as_posix()}',
            lineterm='')
        print('\n'.join(diff))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
