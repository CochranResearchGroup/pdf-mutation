# Release Checklist

Use this checklist before cutting a package release.

## Version

- Confirm `pdf_glyph_replace.__version__` matches `pyproject.toml`.
- Update `CHANGELOG.md` with user-visible behavior, compatibility notes, and
  known limits.
- Confirm `ROADMAP.md` reflects completed and deferred scope.

## Validation

Run source-level checks:

```bash
python3 -m py_compile pdf_glyph_replace.py pdf_fixture.py pdf_inventory.py pdf_dogfood.py pdf_dogfood_summary.py pdf_mutation/*.py
python3 -m unittest discover -s tests -v
```

Validate package installation and metadata in an isolated environment:

```bash
python3 -m venv work/release-venv
work/release-venv/bin/python -m pip install -e .
work/release-venv/bin/pdf-glyph-replace --version
work/release-venv/bin/python -c "from pdf_mutation.engine import plan_qdf; from pdf_mutation import cli; print(plan_qdf.__name__, cli.main.__name__)"
work/release-venv/bin/pdf-fixture-qdf --version
work/release-venv/bin/pdf-inventory --version
work/release-venv/bin/pdf-dogfood --version
work/release-venv/bin/pdf-dogfood-summary --version
work/release-venv/bin/python -m pip wheel . -w work/dist
```

Run the public length-changing PDF smoke:

```bash
work/release-venv/bin/pdf-fixture-qdf 3734 --pdf --one-glyph-per-line --x 653.375 --y 1370 -o work/release.public-length.pdf
work/release-venv/bin/pdf-glyph-replace work/release.public-length.pdf 3734 13846 --align left -o work/release.public-length-left.pdf --report work/release.public-length-left.json --bbox-dir work/release.public-length-left-bbox
work/release-venv/bin/pdf-glyph-replace work/release.public-length.pdf 3734 13846 --align right -o work/release.public-length-right.pdf --report work/release.public-length-right.json --bbox-dir work/release.public-length-right-bbox
qpdf --check work/release.public-length-left.pdf
qpdf --check work/release.public-length-right.pdf
pdftotext work/release.public-length-left.pdf - | rg '13846|3734'
pdftotext work/release.public-length-right.pdf - | rg '13846|3734'
python3 - <<'PY'
import json
from pathlib import Path

for name in ("left", "right"):
    report = json.loads(Path(f"work/release.public-length-{name}.json").read_text())
    assert report["layout_evidence"]["status"] == "ok"
    assert report["layout_evidence"]["alignment_assertions"]["status"] == "ok"
PY
```

When local PDF smoke fixtures are available, run:

```bash
work/release-venv/bin/pdf-glyph-replace tmp.before-travel.pdf 3807 8304 -o work/release.8304.pdf --report work/release.8304.report.json
qpdf --check work/release.8304.pdf
pdftotext work/release.8304.pdf - | rg '8304|3807'

set +e
work/release-venv/bin/pdf-glyph-replace tmp.before-travel.pdf 37.34 138.46 --align right --plan work/release.amount.plan.json --json
amount_plan_rc=$?
set -e
test "$amount_plan_rc" -eq 2
```

Do not create amount-mutated PDFs from private financial fixtures as release
evidence. Use the public length-changing fixture above for positive
length-changing evidence and private amount-like fixtures only for dry-run or
plan-only checks.

## Git

- Confirm generated files under `work/`, package build directories, Python
  caches, and private `tmp*.pdf` files are ignored.
- Commit a coherent release-ready source state.
- Tag the release from the validated commit:

```bash
git tag -a vX.Y.Z -m "vX.Y.Z"
```

Do not tag until validation has passed on the exact commit being tagged.

## Post-Release

After the tag workflow uploads release assets, install the published wheel from
GitHub in a fresh environment outside the source checkout:

```bash
SMOKE_ROOT="$(mktemp -d /tmp/pdf-mutation-release-smoke.XXXXXX)"
python3 -m venv "$SMOKE_ROOT/venv"
"$SMOKE_ROOT/venv/bin/python" -m pip install --upgrade pip
"$SMOKE_ROOT/venv/bin/python" -m pip install \
  "https://github.com/CochranResearchGroup/pdf-mutation/releases/download/vX.Y.Z/pdf_mutation-X.Y.Z-py3-none-any.whl"
cp tests/fixtures/dogfood-manifest.jsonl "$SMOKE_ROOT/dogfood-manifest.jsonl"
cd "$SMOKE_ROOT"
venv/bin/pdf-glyph-replace --version
venv/bin/pdf-fixture-qdf --version
venv/bin/pdf-inventory --version
venv/bin/pdf-dogfood --version
venv/bin/pdf-dogfood-summary --version
venv/bin/pdf-dogfood-summary dogfood-manifest.jsonl --latest-by-policy
set +e
venv/bin/pdf-dogfood-summary dogfood-manifest.jsonl --health
health_rc=$?
set -e
test "$health_rc" -eq 2
venv/bin/python - <<'PY'
import importlib.metadata
import pdf_glyph_replace

print(importlib.metadata.version("pdf-mutation"))
print(pdf_glyph_replace.__file__)
PY
```

Confirm the printed import path is under the smoke venv `site-packages`, not
the repo checkout.
