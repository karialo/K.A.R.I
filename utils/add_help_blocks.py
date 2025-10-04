#!/usr/bin/env python3
"""
utils/add_help_blocks.py

Add a meta_data["help"] block + a help() method to modules that don't have them yet.
- Idempotent: skips files that already define "help" in meta_data and a help() method.
- Conservative: makes a .bak next to every modified file.
- Tries to infer the main class name from the filename (CamelCase), else uses the first class.
"""
from __future__ import annotations
import argparse, ast, pathlib, re, textwrap, shutil, sys
from typing import Optional, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
SEARCH_DIRS = [ROOT / "internal", ROOT / "prosthetics"]

HELP_METHOD_SRC = """
    def help(self, topic: str | None = None) -> str:
        \"\"\"Return human-friendly help text from meta_data['help'].

        Usage:
          - No topic: module overview (the '_module' entry)
          - With topic: an action name (e.g., 'scan', 'public_ip'); hyphens are normalized.
        \"\"\"
        h = getattr(self, "meta_data", {}).get("help", {})
        if not topic:
            return h.get("_module", f"{self.name} — no help available.")
        t = topic.replace("-", "_")
        return h.get(t, f"No help for '{topic}'.")
"""

def camelize(filename: str) -> str:
    base = pathlib.Path(filename).stem
    return "".join(p.capitalize() for p in re.split(r"[_\-]+", base))

def load_ast(path: pathlib.Path) -> ast.Module:
    src = path.read_text(encoding="utf-8")
    return ast.parse(src)

def find_meta_data(module: ast.Module) -> Optional[ast.Assign]:
    for node in module.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "meta_data":
                    return node
    return None

def find_class_name(module: ast.Module, preferred: str) -> Optional[str]:
    # exact match first
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == preferred:
            return node.name
    # otherwise first class
    for node in module.body:
        if isinstance(node, ast.ClassDef):
            return node.name
    return None

def class_has_help_method(module: ast.Module, class_name: str) -> bool:
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for b in node.body:
                if isinstance(b, ast.FunctionDef) and b.name == "help" and len(b.args.args) >= 1:
                    return True
    return False

def get_actions_from_meta(meta_node: ast.Assign) -> list[str]:
    # Best-effort literal eval of the meta_data dict
    try:
        value = ast.literal_eval(meta_node.value)
        if isinstance(value, dict):
            acts = value.get("actions") or []
            if isinstance(acts, (list, tuple)):
                return [str(a) for a in acts]
    except Exception:
        pass
    return []

def already_has_help_key(meta_node: ast.Assign) -> bool:
    try:
        v = ast.literal_eval(meta_node.value)
        return isinstance(v, dict) and "help" in v
    except Exception:
        # If we can't eval, fall back to a quick source check
        return "help" in ast.get_source_segment(open(__file__, 'r', encoding='utf-8').read(), meta_node)

def inject_help_block(src: str, meta_node: ast.Assign, actions: list[str], module_name_friendly: str) -> str:
    # Insert a help block right before the closing '}' of meta_data dict.
    # We’ll find the text slice for meta_data and inject a pretty block.
    start = meta_node.value.col_offset
    ln0 = meta_node.lineno - 1
    lines = src.splitlines()
    # Determine the span of the dict in text
    # We'll walk forward from meta_node.value to find matching closing brace by naive brace counting.
    text_from = "\n".join(lines[ln0:])
    # locate first '{' from value start
    try:
        dict_start = text_from.index("{")
    except ValueError:
        return src  # give up

    brace = 0
    end_idx = None
    for i, ch in enumerate(text_from[dict_start:], start=dict_start):
        if ch == "{":
            brace += 1
        elif ch == "}":
            brace -= 1
            if brace == 0:
                end_idx = i
                break
    if end_idx is None:
        return src  # give up safely

    dict_block = text_from[dict_start:end_idx+1]
    indent = re.match(r"(\s*)", lines[ln0]).group(1) if re.match(r"(\s*)", lines[ln0]) else ""

    # Build the help dictionary
    def help_entry(name: str, body: str) -> str:
        return f'{indent}    "{name}": (\n{textwrap.indent(body, indent + "        ")}\n{indent}    ),\n'

    module_help_text = (
        f"{module_name_friendly} — module help.\n\n"
        "Design notes:\n"
        " - Actions accept either JSON kwargs (via `kari call ... '{\"k\":\"v\"}'`) or a raw string the module parses.\n"
        " - `kari help <ModuleName>` shows this overview; `kari call <ModuleName> help '{\"topic\":\"action\"}'` shows per-action help.\n"
    )

    action_help_entries = ""
    for a in actions:
        a_norm = a.replace("-", "_")
        body = (
            "Usage:\n"
            f"  {a} [args]\n\n"
            "JSON example:\n"
            f"  {{\"example_key\":\"value_for_{a_norm}\"}}\n"
        )
        action_help_entries += help_entry(a_norm, body)

    help_block = (
        f'{indent}    "help": {{\n' +
        help_entry("_module", module_help_text) +
        action_help_entries +
        f"{indent}    }},\n"
    )

    # Inject just before the closing brace of meta_data dict content
    injected = dict_block[:-1]  # drop final "}"
    # If there's already a trailing comma before "}", keep formatting safe
    if not injected.rstrip().endswith(","):
        injected += ","
    injected += "\n" + help_block + indent + "}"

    # Replace dict_block in the overall source
    new_text_from = text_from[:dict_start] + injected + text_from[end_idx+1:]
    new_src = "\n".join(lines[:ln0]) + "\n" + new_text_from
    return new_src

def insert_help_method(src: str, class_name: str) -> str:
    # Find class line and insert method at end of class (before the next top-level def/class or EOF).
    pattern = re.compile(rf"^class\s+{re.escape(class_name)}\s*\(.*?\):", re.M)
    m = pattern.search(src)
    if not m:
        return src
    class_start = m.end()
    # Find the indentation level of the class body
    after_header = src[class_start:].splitlines(True)
    if not after_header:
        return src
    # Find first indented line to measure indent; else default 4 spaces
    indent = "    "
    for line in after_header:
        if line.strip() == "":
            continue
        leading = re.match(r"^(\s+)", line)
        if leading:
            indent = leading.group(1)
        break

    help_method = textwrap.indent(HELP_METHOD_SRC.strip("\n") + "\n", indent)
    # Insert before the next top-level class/def (column 0) or at EOF
    top_level = re.compile(r"^(class\s+|def\s+)", re.M)
    rest = src[class_start:]
    nxt = top_level.search(rest)
    insert_at = class_start + (nxt.start() if nxt else len(rest))
    return src[:insert_at] + help_method + src[insert_at:]

def process_file(path: pathlib.Path, dry: bool) -> Tuple[bool, str]:
    try:
        src = path.read_text(encoding="utf-8")
        mod = ast.parse(src)
        meta = find_meta_data(mod)
        if not meta:
            return False, "no meta_data"
        actions = get_actions_from_meta(meta)
        have_help_key = False
        try:
            v = ast.literal_eval(meta.value)
            have_help_key = isinstance(v, dict) and ("help" in v)
        except Exception:
            # fall back to a substring scan inside the meta_data node span
            have_help_key = '"help"' in src

        class_name = find_class_name(mod, camelize(path.name))
        has_help_method = class_name and class_has_help_method(mod, class_name)

        changed = False
        out = src

        if not have_help_key:
            out = inject_help_block(out, meta, actions, path.stem.replace("_", " ").title())
            changed = True

        if class_name and not has_help_method:
            out = insert_help_method(out, class_name)
            changed = True

        if changed and not dry:
            bak = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, bak)
            path.write_text(out, encoding="utf-8")
        return changed, ("updated" if changed else "ok")
    except Exception as e:
        return False, f"error: {e}"

def main():
    ap = argparse.ArgumentParser(description="Inject help blocks into modules.")
    ap.add_argument("--dry-run", action="store_true", help="Do not write files; just report.")
    ap.add_argument("--only", nargs="*", help="Limit to files matching these substrings.")
    args = ap.parse_args()

    targets = []
    for d in SEARCH_DIRS:
        if not d.exists():
            continue
        targets += list(d.rglob("*.py"))

    if args.only:
        keys = [s.lower() for s in args.only]
        targets = [p for p in targets if any(k in str(p).lower() for k in keys)]

    total_changed = 0
    for p in sorted(targets):
        changed, msg = process_file(p, args.dry_run)
        status = "CHANGED" if changed else "SKIP"
        if changed:
            total_changed += 1
        print(f"{status:7}  {p.relative_to(ROOT)}  ({msg})")

    if args.dry_run:
        print(f"\n[DRY-RUN] Would change: {total_changed} file(s)")
    else:
        print(f"\nDone. Changed: {total_changed} file(s)")

if __name__ == "__main__":
    sys.exit(main())
