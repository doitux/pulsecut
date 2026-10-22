#!/usr/bin/env python3
"""Lists all texts of the web interface that go through T() and checks that each has an English translation.

    python3 tools/i18n_keys.py          # check (exit code 1 if something is missing or unused)
    python3 tools/i18n_keys.py --list   # print all keys
"""
import json
import re
import sys
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "pulsecut" / "ui"


def _skip_string(s, i, q):
    i += 1
    while s[i] != q:
        i += 2 if s[i] == "\\" else 1
    return i + 1


def _skip_template(s, i):
    """i points at the opening backtick; returns (end index, literal parts)."""
    i += 1
    parts, cur = [], ""
    while True:
        c = s[i]
        if c == "\\":
            cur += s[i:i + 2]
            i += 2
        elif c == "`":
            parts.append(cur)
            return i + 1, parts
        elif c == "$" and s[i + 1] == "{":
            parts.append(cur)
            cur = ""
            i = _skip_expr(s, i + 2)
        else:
            cur += c
            i += 1


def _skip_expr(s, i):
    depth = 1
    while depth:
        c = s[i]
        if c in "\"'":
            i = _skip_string(s, i, c)
            continue
        if c == "`":
            i, _ = _skip_template(s, i)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return i


def keys(src):
    out = []
    for m in re.finditer(r"(?<![\w$.])[TN](`|\(\")", src):
        i = m.start() + 1
        if src[i] == "`":
            _, parts = _skip_template(src, i)
            key = "".join(p + (f"{{{k}}}" if k < len(parts) - 1 else "") for k, p in enumerate(parts))
        else:
            j = _skip_string(src, i + 1, '"')
            key = json.loads(src[i + 1:j])
        out.append(key.replace("\\`", "`"))
    return list(dict.fromkeys(out))


def dictionary():
    txt = (UI / "i18n.js").read_text(encoding="utf-8")
    body = txt[txt.index("const EN = {") + len("const EN = "):txt.index("\n};", txt.index("const EN = {")) + 2]
    return json.loads(body)


def python_keys():
    """Texts in L("…") calls of the Python modules (implicitly concatenated literals included)."""
    import ast
    out = []
    for f in sorted((UI.parent).glob("*.py")):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("L", "_t") and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                out.append(node.args[0].value)
    return list(dict.fromkeys(out))


def placeholders(s):
    return sorted(re.findall(r"\{(\w*)\}", s))


def check_python():
    sys.path.insert(0, str(UI.parent.parent))
    from pulsecut.i18n import EN
    used = python_keys()
    bad = 0
    for k in used:
        if k not in EN:
            print("missing (py):", k)
            bad += 1
        elif placeholders(k) != placeholders(EN[k]):
            print("placeholders differ (py):", k)
            bad += 1
    print(f"{len(used)} Python texts, {bad} problems")
    return bad


def main():
    bad_py = check_python()
    used = keys((UI / "app.js").read_text(encoding="utf-8"))
    if "--list" in sys.argv:
        print(json.dumps(used, ensure_ascii=False, indent=1))
        return 0
    have = dictionary()
    missing = [k for k in used if k not in have]
    extra = [k for k in have if k not in used]
    for k in missing:
        print("missing:", k)
    for k in extra:
        print("unused: ", k)
    wrong = [k for k in used if k in have and placeholders(k) != placeholders(have[k])]
    for k in wrong:
        print("placeholders differ:", k)
    print(f"{len(used)} interface texts, {len(missing)} missing, {len(extra)} unused, {len(wrong)} placeholder problems")
    return 1 if missing or extra or wrong or bad_py else 0


if __name__ == "__main__":
    sys.exit(main())
