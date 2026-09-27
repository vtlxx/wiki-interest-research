import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", ROOT / "DESIGN.md", ROOT / "DEVELOPMENT.md", ROOT / "examples" / "README.md",
        *sorted((ROOT / "references").glob("*.md"))]
LINK = re.compile(r"\]\(([^)\s]+)\)")
TEST_REF = re.compile(r"tests/(test_\w+\.py)::(test_\w+)")


def _anchors(path: Path) -> set[str]:
    """GitHub-style heading anchors of a Markdown file."""
    out = set()
    for line in path.read_text("utf-8").splitlines():
        if line.startswith("#"):
            text = line.lstrip("#").strip().lower()
            out.add(re.sub(r"[^\w\- ]", "", text).replace(" ", "-"))
    return out


def test_every_relative_link_resolves():
    for doc in DOCS:
        for target in LINK.findall(doc.read_text("utf-8")):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            file_part, _, anchor = target.partition("#")
            path = (doc.parent / file_part).resolve() if file_part else doc
            assert path.exists(), f"{doc.name}: broken link {target}"
            if anchor and path.suffix == ".md":
                assert anchor in _anchors(path), f"{doc.name}: no heading for #{anchor} in {path.name}"


def test_tests_named_in_design_exist():
    refs = TEST_REF.findall((ROOT / "DESIGN.md").read_text("utf-8"))
    assert len(refs) >= 20
    for file, name in refs:
        source = (ROOT / "tests" / file).read_text("utf-8")
        assert re.search(rf"^def {name}\(", source, re.M), f"{file}::{name} does not exist"


def test_examples_exist_and_stay_small():
    readme = (ROOT / "README.md").read_text("utf-8")
    referenced = set(re.findall(r"examples/([\w.\-]+\.(?:pdf|png))", readme))
    assert referenced
    for name in referenced:
        assert (ROOT / "examples" / name).is_file(), name
    total = sum(p.stat().st_size for p in (ROOT / "examples").iterdir() if p.is_file())
    assert total <= 3 * 1024 * 1024
