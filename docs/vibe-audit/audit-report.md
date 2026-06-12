# Vibe Security & Architecture Audit Report

---
report-version: 1.1.3
audit-date: 2026-06-13
target: md-converters v1.1.0
auditor: Mistral Vibe (CLI coding agent), verified by Codex
status: READY FOR PRODUCTION
previous-audit: 1.1.2
evidence-dir: docs/vibe-audit/evidence/2026-06-13
---

## Executive Summary

Repository-wide security and architecture review was completed on 2026-06-13.
The ten findings from the previous audit cycle were either fixed or proven not
to be defects. The product version is now `md-converters 1.1.0`; the package
metadata, CLI behavior, README, CODEX plan, CI workflow, lockfile, SBOM/SCA
evidence, and local installation procedure are aligned with that version.

This report corrects the v1.1.0 audit-report inaccuracies:

- generated audit artifacts are committed under
  `docs/vibe-audit/evidence/2026-06-13`, not left as root-level untracked files;
- runtime and development dependency graphs are audited separately;
- runtime license inventory is measured on a runtime-only environment;
- `tests/test_entrypoints_and_interactive.py` has 66 lines, not 79;
- final repository cleanliness is verified after this closing commit is pushed.

It also records three GitHub CI findings discovered after the first closing
push:

- Python 3.14 initially failed because the resolver selected
  `magika 0.6.3 -> onnxruntime 1.20.1`, and `onnxruntime 1.20.1` has no
  `cp314` wheels. The project now constrains `magika>=0.6.2,<0.6.3` and the
  lock resolves Python >=3.11 to `onnxruntime 1.26.0`; Linux 3.14 and Windows
  3.14 are both covered.
- The license gate no longer treats long package notice text as an SPDX-style
  license declaration when a package already provides authoritative
  classifier/expression metadata. This removes a false positive where the Linux
  `pandas` wheel is BSD-licensed but its bundled notices mention GPL in
  historical Python license text.
- The repeat-without-`--force` smoke check now verifies that the output file
  hash remains unchanged instead of depending on a localized stdout phrase.

## Current Product State

| Metric | Verified Value |
|--------|----------------|
| Product version | `md-converters 1.1.0` |
| Tests | `41 passed` |
| Lint | `ruff check convert_to_md.py tests tools` passed |
| Compilation | `py_compile convert_to_md.py tools/supply_chain_report.py` passed |
| SBOM | CycloneDX runtime + development SBOM generated |
| SCA | runtime + development `pip-audit`: no known vulnerabilities |
| Runtime license policy | 41 packages, 0 unknown, 0 forbidden |
| Dev license evidence | 65 packages, 0 unknown, 0 forbidden |
| CI matrix | Linux Python 3.10, 3.11, 3.12, 3.13, 3.14 + Windows 3.12, 3.14 |

## Evidence Files

The following generated evidence is intentionally committed:

- `docs/vibe-audit/evidence/2026-06-13/cyclonedx-runtime-sbom.json`
- `docs/vibe-audit/evidence/2026-06-13/cyclonedx-dev-sbom.json`
- `docs/vibe-audit/evidence/2026-06-13/requirements-runtime-audit.txt`
- `docs/vibe-audit/evidence/2026-06-13/requirements-dev-audit.txt`
- `docs/vibe-audit/evidence/2026-06-13/supply-chain-licenses.json`
- `docs/vibe-audit/evidence/2026-06-13/supply-chain-dev-licenses.json`

CI still regenerates these artifacts independently on every run. The committed
copies are audit evidence for this closing review, not the source of truth for
future dependency updates.

## Findings Closure

### 1. Git Status Discrepancy

Status: closed as reporting issue.

The earlier `origin/main..HEAD = 0` observation was expected immediately after
push. The v1.1.0 report later became stale because the report itself and root
generated artifacts were local-only. This v1.1.1 report fixes that by committing
the evidence under `docs/vibe-audit/evidence/2026-06-13` and requiring a final
`pull --rebase` + `push` closure.

### 2. Insecure `data:` URI Validation

Status: fixed.

`_SAFE_DATA_IMAGE` now accepts only supported image MIME types and strict
base64 with valid padding. Whitespace and mixed payload garbage are rejected.
Regression coverage: `test_safe_data_image_requires_strict_base64_when_images_kept`.

### 3. Incomplete SBOM Generation

Status: fixed.

The supply-chain job now generates:

- `cyclonedx-runtime-sbom.json`
- `cyclonedx-dev-sbom.json`

Runtime and development graphs are separated so operational dependencies and
tooling dependencies can be reviewed independently.

### 4. `pip-audit` Outside Locked Environment

Status: fixed.

`pip-audit` runs through `uv run --frozen pip-audit`, using the locked dev
environment rather than an unconstrained `uvx` tool environment. The added dev
audit caught `CVE-2025-71176` in `pytest 8.4.2`; `pytest` is now locked at
`9.0.3`.

### 5. Subprocess Error Masking

Status: fixed.

Worker stdout/stderr decoding now uses `errors="strict"` and handles
`UnicodeDecodeError` explicitly. Regression coverage:
`test_subprocess_runner_fails_on_non_utf8_worker_output`.

### 6. Source ID Collision Risk

Status: fixed.

`source_id` now uses a 128-bit SHA-256 prefix (32 hex characters). Legacy
16-hex identifiers remain compatible through `_source_id_matches()`, so
previously generated Markdown files can still be matched.

### 7. Missing Direct Dependency

Status: fixed.

`charset-normalizer>=3,<4` is now a direct runtime dependency because
`decode_html_bytes()` imports it directly.

### 8. HTML Decode Fallback Traceability

Status: fixed.

The last-resort fallback now reports `cp1251-replace` instead of silently
claiming a clean `cp1251` decode.

### 9. Missing Python 3.11 in CI

Status: fixed.

The Linux matrix now covers Python 3.10, 3.11, 3.12, 3.13, and 3.14. Windows
smoke coverage covers Python 3.12 and 3.14.

Python 3.14 coverage is supported by constraining `magika` below 0.6.3 until
upstream releases a dependency graph that does not resolve to the
Python-3.14-incompatible `onnxruntime 1.20.1`.

### 10. Test Coverage Gaps

Status: fixed.

Coverage was added for:

- `cli_pdf()` / `cli_html()`;
- `--version`;
- `_download_url()` redirect handling;
- `_worker_convert()`;
- interactive overwrite confirmation;
- strict `data:` image validation;
- 128-bit `source_id` and legacy prefix matching;
- strict worker output decoding;
- explicit `cp1251-replace` fallback.

## Verification Commands

The following commands were run in the closing pass:

```powershell
uv lock --check
py -3.14 -m py_compile convert_to_md.py tools/supply_chain_report.py
uv run --frozen ruff check convert_to_md.py tests tools
uv run --frozen pytest -q
uv --quiet export --format requirements.txt --no-dev --no-emit-project --locked --output-file docs/vibe-audit/evidence/2026-06-13/requirements-runtime-audit.txt
uv --quiet export --format requirements.txt --all-groups --no-emit-project --locked --output-file docs/vibe-audit/evidence/2026-06-13/requirements-dev-audit.txt
uv --quiet export --format cyclonedx1.5 --no-dev --locked --output-file docs/vibe-audit/evidence/2026-06-13/cyclonedx-runtime-sbom.json
uv --quiet export --format cyclonedx1.5 --all-groups --locked --output-file docs/vibe-audit/evidence/2026-06-13/cyclonedx-dev-sbom.json
uv sync --frozen --no-dev
uv run --frozen --no-dev python tools/supply_chain_report.py --output docs/vibe-audit/evidence/2026-06-13/supply-chain-licenses.json --fail-on-forbidden
uv sync --frozen
uv run --frozen pip-audit --progress-spinner off -r docs/vibe-audit/evidence/2026-06-13/requirements-runtime-audit.txt
uv run --frozen pip-audit --progress-spinner off -r docs/vibe-audit/evidence/2026-06-13/requirements-dev-audit.txt
uv run --frozen tomd --version
tomd --version
```

## Standards Mapping

| Control Area | Implementation Evidence |
|--------------|-------------------------|
| NIST SSDF PS.3 / RV.1 | `uv.lock`, SBOM export, `pip-audit`, Dependabot |
| ISO/IEC 27001 A.8.8 | dependency inventory and vulnerability monitoring |
| SLSA supply-chain discipline | locked dependencies, reproducible CI install |
| CycloneDX | runtime and development SBOM artifacts |
| OWASP SSRF / CWE-918 | URL scheme allowlist, DNS/IP public-address checks, redirect re-check |
| CWE-400 | URL/file size limits and conversion timeout |
| CWE-79 / CWE-116 | Markdown link/HTML sanitization and strict safe `data:` policy |

## Conclusion

`md-converters v1.1.0` is ready for production use as a local document-to-
Markdown utility for trusted users processing potentially untrusted documents
with defense-in-depth controls. The remaining operational requirement is to
verify GitHub Actions after the final push, because local validation cannot
prove hosted runner behavior.
