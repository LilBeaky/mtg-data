#!/usr/bin/env python3
"""Write translation/prototype/vocabulary.md: every GEF construct with its exact fields and allowed values, generated
from translation/gef_schema.py so the translator's reference can't drift from the schema. Required fields end in *.

  python3 translation/make_vocab.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gef_schema as S                                   # noqa: E402

NAMED = [("Amount", S.AMOUNT), ("Cost", S.COST), ("Mana", S.MANA), ("Target", S.TARGET), ("Token", S.TOKEN),
         ("Player", S.PLAYER), ("Zone", S.ZONE), ("Duration", S.DURATION), ("ColorSet", S.COLORSET), ("ManaCost", S.MANA_COST),
         ("Event", S.EVENT), ("PermFilter", S.PERM_FILTER), ("CardFilter", S.CARD_FILTER)]

def show(s, top=False):
    """A field schema as a short type string (shared shapes by name)."""
    if not top:
        for name, shape in NAMED:
            if s is shape or s == shape: return name
    if "$ref" in s: return s["$ref"].split("/")[-1]
    if "enum" in s: return " | ".join(map(str, s["enum"]))
    if "const" in s: return repr(s["const"])
    if "anyOf" in s: return " or ".join(show(x) for x in s["anyOf"])
    t = s.get("type")
    if t == "array": return "[" + show(s["items"]) + "]"
    if t == "object": return "{" + ", ".join(k + ("*" if k in s.get("required", []) else "") for k in s.get("properties", {})) + "}"
    if "pattern" in s: return f"string matching {s['pattern']}"
    return t or "?"

def cases(title, tag, table, out):
    out.append(f"\n## {title} (`{tag}`)\n")
    for name, spec in table.items():
        props, req = spec if isinstance(spec, tuple) else (spec, [])
        fields = ", ".join(f"`{k}{'*' if k in req else ''}`: {show(v)}" for k, v in props.items()) or "(no fields)"
        out.append(f"- **{name}**: {fields}")

def obj_block(title, s, out):
    out.append(f"\n## {title}\n")
    for k, v in s["properties"].items():
        if v is s: v = {"$ref": title}
        out.append(f"- `{k}{'*' if k in s.get('required', []) else ''}`: {show(v)}")

def main():
    out = ["# GEF 0.1 vocabulary (generated from translation/gef_schema.py; do not edit)",
           "", "Every object is closed: only the fields listed here are allowed. `*` = required. Types refer to the sections below.",
           "Every ability also takes `text` (the Oracle line it translates).",
           "\n## Card\n", "- `gef`*: '0.1'", "- `name`*: the Oracle name", "- `abilities`: [Ability]  (or `faces`: [{`name`*, `abilities`*}] for cards whose faces both have text)",
           "- `notes`: string (anything a reviewer should know)", "- `source`: llm | hand | override | parser_export"]
    cases("Abilities", "kind", S.ABILITY_CASES, out)
    cases("Effects", "do", S.EFFECT_CASES, out)
    cases("Statics", "static", S.STATIC_CASES, out)
    cases("Conditions", "if", S.CONDS, out)
    obj_block("Event", S.EVENT, out)
    out.append("\nEvent `on` values: " + ", ".join(S.EVENTS))
    obj_block("PermFilter (a permanent)", S.PERM_FILTER, out)
    obj_block("CardFilter (a card in a zone, or a spell)", S.CARD_FILTER, out)
    obj_block("Target", S.TARGET, out)
    obj_block("Token", S.TOKEN, out)
    obj_block("Mana (what a mana ability or ritual produces)", S.MANA, out)
    obj_block("Cost (every part the ability needs paid)", S.COST, out)
    out.append("\n- Player: " + ", ".join(S.PLAYER["enum"]))
    out.append("\n## Amount\n\nAn integer, \"X\" (the spell's or ability's X), or an object:\n")
    obj_block("Amount object", S.AMOUNT["anyOf"][2], out)
    out.append("\nAmount `count` keys: " + ", ".join(S.COUNT["enum"]))
    out.append("\n## Shared value lists\n")
    out.append("- Player (`who`): " + ", ".join(S.PLAYER["enum"]))
    out.append("- Zone (`to`, `from`): " + ", ".join(S.ZONE["enum"]))
    out.append("- Duration: " + ", ".join(S.DURATION["enum"]))
    out.append("- Color set (mana `units`, `colors`): " + S.COLORSET["pattern"] + "  (e.g. \"C\", \"G\", \"WU\" = W or U, \"any\")")
    out.append("- Mana cost strings: " + S.MANA_COST["pattern"] + "  (e.g. \"{2}{U}\", \"{X}{R}\", \"{G/P}\")")
    out.append("- Keywords (`keyword`): " + ", ".join(S.KEYWORDS))
    path = os.path.join(HERE, "prototype", "vocabulary.md")
    with open(path, "w", encoding="utf-8") as f: f.write("\n".join(out) + "\n")
    print("wrote", os.path.relpath(path, os.path.dirname(HERE)), f"({sum(len(x) for x in out)} chars)")

if __name__ == "__main__":
    main()
