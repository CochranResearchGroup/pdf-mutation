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
work/release-venv/bin/python -c "from pdf_mutation.engine import plan_qdf; print(plan_qdf.__name__)"
work/release-venv/bin/pdf-fixture-qdf --version
work/release-venv/bin/pdf-inventory --version
work/release-venv/bin/pdf-dogfood --version
work/release-venv/bin/pdf-dogfood-summary --version
work/release-venv/bin/python -m pip wheel . -w work/dist
```

When local PDF smoke fixtures are available, run:

```bash
work/release-venv/bin/pdf-glyph-replace tmp.before-travel.pdf 3807 8304 -o work/release.8304.pdf --report work/release.8304.report.json
qpdf --check work/release.8304.pdf
pdftotext work/release.8304.pdf - | rg '8304|3807'

work/release-venv/bin/pdf-glyph-replace tmp.before-travel.pdf 37.34 138.46 --align right -o work/release.amount.pdf --report work/release.amount.report.json
qpdf --check work/release.amount.pdf
pdftotext work/release.amount.pdf - | rg '138\.46|37\.34'
pdftotext -bbox work/release.amount.pdf work/release.amount.bbox.html
rg '138\.46' work/release.amount.bbox.html
```

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
