"""Verify i18n consistency for the JAOT modules (SPECS §10.5).

Two checks, stdlib only (runs on the CI host and locally, no Odoo):

1. Templates: each committed ``.pot`` must match a fresh regeneration
   (``dev/gen_i18n.py``). The two header lines Odoo re-stamps on every
   export (``POT-Creation-Date`` / ``PO-Revision-Date``) are ignored —
   a fresh export always carries a new date, so a raw byte-diff would
   fail on every run. Any other difference means the committed
   template is stale: the i18n job goes red.

2. Catalogs: every ``.po`` next to its template must stay in sync with
   the template — same set of msgids (nothing missing, nothing stale) —
   and be fully translated (no empty msgstr). A gap means the committed
   catalog lags the strings the template knows about, or ships
   untranslated entries.
"""
import difflib
import pathlib
import re
import subprocess
import sys

# In a .pot the header lives inside a quoted multi-line msgstr, so the
# stamp lines look like: "POT-Creation-Date: 2026-09-19 21:31+0000\n"
STAMP_RE = re.compile(r'^"\s*(POT-Creation-Date|PO-Revision-Date):')
_UNESCAPE = {'"': '"', 'n': '\n', '\\': '\\', 't': '\t', 'r': '\r'}


def normalize(text):
    return '\n'.join(
        line for line in text.splitlines() if not STAMP_RE.match(line))


def _decode(quoted):
    """Join the double-quoted fragments of one msgid/msgstr, unescaped."""
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', quoted)
    return ''.join(
        re.sub(
            r'\\(.)',
            lambda m: _UNESCAPE.get(m.group(1), '\\' + m.group(1)),
            p)
        for p in parts)


def parse_po(path):
    """Return (header_msgstr, {msgid: msgstr}) for a .po or .pot file."""
    entries = {}
    header = ''
    text = path.read_text(encoding='utf-8')
    for block in re.split(r'\n\s*\n', text):
        msgid_q = None
        msgstr_q = None
        mode = None
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('msgid'):
                mode = 'msgid'
                msgid_q = line[5:]
            elif line.startswith('msgstr'):
                mode = 'msgstr'
                msgstr_q = line[6:]
            elif mode and line.startswith('"'):
                if mode == 'msgid':
                    msgid_q += line
                else:
                    msgstr_q += line
        if msgid_q is None:
            continue
        msgid = _decode(msgid_q)
        msgstr = _decode(msgstr_q) if msgstr_q is not None else ''
        if msgid:
            entries[msgid] = msgstr
        else:
            header = msgstr
    return header, entries


def check_template(pot):
    """Phase 1: the committed .pot matches a fresh regeneration."""
    fresh = pot.read_text(encoding='utf-8')
    # A template with no committed version yet is new in this commit
    # cycle: nothing to drift from, so report it and move on.
    try:
        head = subprocess.run(
            ['git', 'show', f'HEAD:{pot.as_posix()}'],
            capture_output=True, check=True).stdout.decode('utf-8')
    except subprocess.CalledProcessError:
        print(f'NEW  {pot.as_posix()} (not in HEAD yet)')
        return False
    if normalize(head) == normalize(fresh):
        print(f'OK   {pot.as_posix()}')
        return False
    print(f'STALE {pot.as_posix()} (differs from HEAD beyond the stamps):')
    diff = difflib.unified_diff(
        normalize(head).splitlines(),
        normalize(fresh).splitlines(),
        fromfile=f'HEAD:{pot.as_posix()}',
        tofile=f'working:{pot.as_posix()}',
        lineterm='')
    print('\n'.join(diff))
    return True


def check_catalogs(pot):
    """Phase 2: every .po next to the template is in sync with it."""
    _, pot_entries = parse_po(pot)
    pos = sorted(pot.parent.glob('*.po'))
    if not pos:
        return False
    failed = False
    for po in pos:
        header, entries = parse_po(po)
        if not re.search(r'Language: \S+', header):
            failed = True
            print(f'BAD  {po.as_posix()} (header has no Language:)')
            continue
        missing = sorted(set(pot_entries) - set(entries))
        extra = sorted(set(entries) - set(pot_entries))
        empty = sorted(m for m, t in entries.items() if not t.strip())
        if missing or extra or empty:
            failed = True
            print(f'GAP  {po.as_posix()}:')
            for m in missing:
                print(f'  missing msgid: {m!r}')
            for m in extra:
                print(f'  stale msgid:   {m!r}')
            for m in empty:
                print(f'  empty msgstr:  {m!r}')
        else:
            print(f'OK   {po.as_posix()} ({len(entries)} entries vs {pot.name})')
    return failed


def main():
    pots = sorted(pathlib.Path('.').glob('*/i18n/*.pot'))
    if not pots:
        print('no .pot templates found — nothing to check', file=sys.stderr)
        return 1
    failed = False
    for pot in pots:
        failed = check_template(pot) or failed
        failed = check_catalogs(pot) or failed
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
