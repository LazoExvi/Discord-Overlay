"""Maintain the real-gameplay regression corpus under tests/corpus/.

    python scripts/build_corpus.py add path/to/log-export.csv [more.csv ...]
        Add the raw OCR lines from chronological log exports to tests/corpus/lines.txt
        (distinct lines, sorted) and regenerate the expected results.

    python scripts/build_corpus.py regenerate
        Re-parse every corpus line with the current parser and rewrite
        tests/corpus/expected.tsv. Run this after an intentional parser change,
        then review the diff of expected.tsv before committing.

    python scripts/build_corpus.py diff
        Show which lines parse differently from expected.tsv (what the test prints).

The corpus contains the character names seen in the contributed logs; contributors
know this before sharing.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from discord_overlay.parser import CombatTextParser  # noqa: E402

CORPUS_DIR = ROOT / "tests" / "corpus"
LINES = CORPUS_DIR / "lines.txt"
EXPECTED = CORPUS_DIR / "expected.tsv"
PLAYER = "Crit"  # the corpus is parsed as this character; "YOU"/"Your" lines resolve to it
FIELDS = ("kind", "actor", "target", "action", "amount", "absorbed", "critical", "pet", "shield")


def load_lines() -> list[str]:
    if not LINES.exists():
        return []
    return [line.rstrip("\n") for line in LINES.read_text(encoding="utf-8").splitlines() if line.strip()]


def save_lines(lines: list[str]) -> None:
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    LINES.write_text("\n".join(sorted(set(lines), key=str.casefold)) + "\n", encoding="utf-8")


def parse_line(parser: CombatTextParser, text: str) -> str:
    event = parser.parse(text, 1.0, 0.0)
    if event is None:
        return "-"
    values = (event.kind.value, event.actor, event.target, event.action, event.amount, event.absorbed,
              int(event.critical), int(event.is_pet), int(event.is_damage_shield))
    return "|".join(str(v) for v in values)


def parse_all(lines: list[str]) -> dict[str, str]:
    # A fresh parser per line: results must not depend on pet names learned from earlier lines.
    return {text: parse_line(CombatTextParser(PLAYER), text) for text in lines}


def load_expected() -> dict[str, str]:
    expected: dict[str, str] = {}
    if EXPECTED.exists():
        for row in EXPECTED.read_text(encoding="utf-8").splitlines():
            if "\t" in row:
                text, result = row.split("\t", 1)
                expected[text] = result
    return expected


def save_expected(results: dict[str, str]) -> None:
    body = "\n".join(f"{text}\t{results[text]}" for text in sorted(results, key=str.casefold))
    EXPECTED.write_text(body + "\n", encoding="utf-8")


def differences(lines: list[str], expected: dict[str, str]) -> list[tuple[str, str, str]]:
    actual = parse_all(lines)
    return [(text, expected.get(text, "<missing>"), actual[text]) for text in lines if expected.get(text) != actual[text]]


def countable(text: str) -> bool:
    """Lines that carry a number are the ones the parser must turn into events."""
    return any(ch.isdigit() for ch in text)


def parsed_share(results: dict[str, str]) -> float:
    numeric = [text for text in results if countable(text)]
    parsed = sum(1 for text in numeric if results[text] != "-")
    return parsed / max(1, len(numeric))


def summary(results: dict[str, str]) -> str:
    numeric = sum(1 for text in results if countable(text))
    unknown = sum(1 for r in results.values() if r != "-" and "|Unknown|" in f"|{r}|")
    return (f"{len(results)} lines, {numeric} with a number of which {100.0 * parsed_share(results):.1f}% parse, "
            f"{unknown} with an Unknown party")


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"add", "regenerate", "diff"}:
        print(__doc__)
        return 2
    command, paths = argv[0], argv[1:]
    lines = load_lines()
    if command == "add":
        added = 0
        for path in paths:
            with Path(path).open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            if not rows or "Raw Text" not in rows[0]:
                print(f"skip {path}: not a chronological log export")
                continue
            before = len(set(lines))
            lines.extend(r["Raw Text"].strip() for r in rows if r["Raw Text"].strip())
            added += len(set(lines)) - before
            print(f"{path}: {len(set(lines)) - before} new distinct lines")
        save_lines(lines)
        lines = load_lines()
        results = parse_all(lines)
        save_expected(results)
        print(f"added {added}; {summary(results)}")
        return 0
    if command == "regenerate":
        results = parse_all(lines)
        changed = sum(1 for t in lines if load_expected().get(t) != results[t])
        save_expected(results)
        print(f"rewrote expected.tsv; {changed} lines changed; {summary(results)}")
        return 0
    diffs = differences(lines, load_expected())
    for text, was, now in diffs:
        print(f"{text}\n    expected {was}\n    now      {now}")
    print(f"{len(diffs)} differences; {summary(parse_all(lines))}")
    return 1 if diffs else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
