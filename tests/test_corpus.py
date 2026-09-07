"""Every real gameplay line in tests/corpus must parse exactly as recorded.

The corpus is raw OCR text from contributed log exports. If a parser change is
intentional, run ``python scripts/build_corpus.py regenerate`` and review the
diff of tests/corpus/expected.tsv; the failure output below lists what moved.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_corpus", ROOT / "scripts" / "build_corpus.py")
build_corpus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_corpus)

MIN_PARSED_SHARE = 0.999  # of lines that carry a number; flavour text without one is expected to be ignored


@pytest.fixture(scope="module")
def corpus():
    lines = build_corpus.load_lines()
    if not lines:
        pytest.skip("no corpus lines")
    return lines, build_corpus.load_expected()


def test_every_corpus_line_parses_as_recorded(corpus):
    lines, expected = corpus
    diffs = build_corpus.differences(lines, expected)
    if diffs:
        shown = "\n".join(f"  {text}\n      expected {was}\n      now      {now}" for text, was, now in diffs[:25])
        more = f"\n  ... and {len(diffs) - 25} more" if len(diffs) > 25 else ""
        pytest.fail(f"{len(diffs)} corpus lines parse differently from tests/corpus/expected.tsv "
                    f"(run scripts/build_corpus.py regenerate if intended):\n{shown}{more}")


def test_corpus_coverage_does_not_regress(corpus):
    lines, _expected = corpus
    results = build_corpus.parse_all(lines)
    assert build_corpus.parsed_share(results) >= MIN_PARSED_SHARE, build_corpus.summary(results)
