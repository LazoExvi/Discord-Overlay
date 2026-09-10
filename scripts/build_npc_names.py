"""Refresh discord_overlay/assets/npc-names.txt from the community NPC lists.

    python scripts/build_npc_names.py

Sources (both community-maintained, neither complete):
  * Monsters & Memories wiki, Category:NPCs and its subcategories
    https://monstersandmemories.miraheze.org/wiki/Category:NPCs
  * mnmdrops.com/mobs

The list is a hint for display-time name merging: a rare misspelling that is one
OCR confusion away from a known NPC snaps to the NPC's spelling even when the
correct spelling was never read that fight. It is never used to reject a name.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "discord_overlay" / "assets" / "npc-names.txt"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DiscordOverlay-npc-list/1.0"
WIKI_API = "https://monstersandmemories.miraheze.org/w/api.php"
DROPS_URL = "https://mnmdrops.com/mobs"
QUALIFIER = re.compile(r"\s*\((?:[^()]*)\)\s*$")


HEADERS = {"User-Agent": UA, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-US,en;q=0.9"}


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def wiki_category(category: str):
    cont: dict[str, str] = {}
    while True:
        params = {"action": "query", "list": "categorymembers", "cmtitle": category, "cmlimit": "500",
                  "format": "json", **cont}
        data = json.loads(fetch(WIKI_API + "?" + urllib.parse.urlencode(params)))
        yield from ((m["ns"], m["title"]) for m in data["query"]["categorymembers"])
        if "continue" not in data:
            return
        cont = {"cmcontinue": data["continue"]["cmcontinue"]}
        time.sleep(0.3)


def wiki_names() -> set[str]:
    names, seen, queue = set(), set(), ["Category:NPCs"]
    while queue:
        category = queue.pop()
        if category in seen:
            continue
        seen.add(category)
        for ns, title in wiki_category(category):
            if ns == 14:
                queue.append(title)
            elif ns == 0:
                names.add(title)
        print(f"  {category}: {len(names)} names so far", file=sys.stderr)
        time.sleep(0.3)
    return names


def drops_names() -> set[str]:
    html = fetch(DROPS_URL).decode("utf-8", "replace")
    # The page embeds its data as escaped JSON: \"name\":\"Bone Construct\"
    return {json.loads(f'"{m}"') for m in re.findall(r'\\"name\\":\\"((?:[^"\\]|\\\\.)+?)\\"', html)}


def clean(name: str) -> str | None:
    name = QUALIFIER.sub("", name).strip()
    name = name.replace("’", "'").replace("`", "'")
    if not name or "/" in name or name.casefold() in {"unknown", "quest", "leatherworking"}:
        return None
    if not re.search(r"[A-Za-z]", name) or len(name) < 3:
        return None
    return re.sub(r"\s+", " ", name)


def existing_names() -> set[str]:
    if not ASSET.exists():
        return set()
    return {line.strip() for line in ASSET.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")}


def main() -> int:
    # Names are only ever added. A source that is unreachable (the wiki answers 403 to
    # some hosting networks) keeps its previously gathered names from the committed file.
    raw = existing_names()
    succeeded = 0
    for label, source in (("wiki", wiki_names), ("mnmdrops", drops_names)):
        print(f"{label}...", file=sys.stderr)
        try:
            raw |= source()
            succeeded += 1
        except Exception as exc:  # noqa: BLE001 - one blocked site must not lose the other
            print(f"  {label} unavailable ({type(exc).__name__}: {exc}); keeping its committed names", file=sys.stderr)
    if not succeeded:
        print("no source reachable; list left unchanged", file=sys.stderr)
        return 1
    by_key: dict[str, str] = {}
    for name in sorted(raw):
        cleaned = clean(name)
        if cleaned is None:
            continue
        key = re.sub(r"^(?:a|an|the)\s+", "", cleaned, flags=re.IGNORECASE).casefold()
        # Prefer the wiki's capitalisation (lowercase generic mobs) over title case.
        current = by_key.get(key)
        if current is None or (current.istitle() and not cleaned.istitle()):
            by_key[key] = cleaned
    lines = ["# NPC names from the Monsters & Memories community wiki (Category:NPCs) and mnmdrops.com.",
             "# Regenerate with: python scripts/build_npc_names.py",
             "# One name per line; a leading article is kept as written but ignored when matching.", ""]
    lines += sorted(by_key.values(), key=str.casefold)
    ASSET.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(by_key)} names to {ASSET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
