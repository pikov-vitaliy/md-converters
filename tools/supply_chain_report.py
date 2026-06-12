"""Generate JSON license inventory for the active Python environment."""

from __future__ import annotations

import argparse
import json
import platform
import re
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path


DEFAULT_FORBIDDEN_LICENSE_PATTERNS = (
    "agpl",
    "affero",
    "gpl",
    "lgpl",
    "sspl",
    "commons clause",
    "sleepycat",
)

BOOTSTRAP_PACKAGES = {
    "pip",
    "setuptools",
    "wheel",
}

LICENSE_PATTERN_ALIASES = {
    "agpl": ("agpl", "affero general public license"),
    "gpl": ("gpl", "general public license"),
    "lgpl": (
        "lgpl",
        "library general public license",
        "lesser general public license",
    ),
    "sspl": ("sspl", "server side public license"),
}


@dataclass(frozen=True)
class PackageLicense:
    name: str
    version: str
    license_expression: str
    license_text: str
    license_classifiers: tuple[str, ...]
    summary: str
    home_page: str

    @property
    def normalized_license(self) -> str:
        parts = [
            self.license_expression,
            self.license_text,
            *self.license_classifiers,
        ]
        visible = [part.strip() for part in parts if part and part.strip()]
        return " | ".join(visible) if visible else "UNKNOWN"


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _metadata_value(dist: metadata.Distribution, field: str) -> str:
    value = dist.metadata.get(field, "")
    return " ".join(value.split())


def _license_classifiers(dist: metadata.Distribution) -> tuple[str, ...]:
    classifiers = dist.metadata.get_all("Classifier") or []
    licenses = [
        " :: ".join(classifier.split(" :: ")[1:])
        for classifier in classifiers
        if classifier.startswith("License :: ")
    ]
    return tuple(sorted(set(licenses)))


def collect_packages(
    *,
    exclude: set[str] | None = None,
) -> list[PackageLicense]:
    excluded = {_canonical_name(name) for name in (exclude or set())}
    packages: list[PackageLicense] = []
    for dist in metadata.distributions():
        name = _metadata_value(dist, "Name")
        if not name or _canonical_name(name) in excluded:
            continue
        packages.append(
            PackageLicense(
                name=name,
                version=_metadata_value(dist, "Version"),
                license_expression=_metadata_value(dist, "License-Expression"),
                license_text=_metadata_value(dist, "License"),
                license_classifiers=_license_classifiers(dist),
                summary=_metadata_value(dist, "Summary"),
                home_page=_metadata_value(dist, "Home-page"),
            )
        )
    return sorted(packages, key=lambda package: _canonical_name(package.name))


def forbidden_matches(
    package: PackageLicense,
    forbidden_patterns: tuple[str, ...],
) -> list[str]:
    license_text = package.normalized_license.lower()
    matches: list[str] = []
    for pattern in forbidden_patterns:
        normalized = pattern.strip().lower()
        if not normalized:
            continue
        aliases = LICENSE_PATTERN_ALIASES.get(normalized, (normalized,))
        if any(
            _contains_license_pattern(license_text, alias)
            for alias in aliases
        ):
            matches.append(pattern)
    return matches


def _contains_license_pattern(license_text: str, pattern: str) -> bool:
    if pattern in {"agpl", "gpl", "lgpl", "sspl"}:
        pattern_re = (
            rf"(?<![a-z0-9]){re.escape(pattern)}"
            r"(?:[- ]?v?\d+(?:\.\d+)*)?"
            r"(?![a-z0-9])"
        )
    else:
        pattern_re = rf"(?<![a-z0-9]){re.escape(pattern)}(?![a-z0-9])"
    return re.search(pattern_re, license_text) is not None


def build_report(
    packages: list[PackageLicense],
    *,
    forbidden_patterns: tuple[str, ...],
    fail_on_forbidden: bool,
) -> dict[str, object]:
    issues: list[dict[str, str]] = []
    unknown_licenses = 0
    for package in packages:
        if package.normalized_license == "UNKNOWN":
            unknown_licenses += 1
        for pattern in forbidden_matches(package, forbidden_patterns):
            issues.append(
                {
                    "severity": "error" if fail_on_forbidden else "warning",
                    "type": "forbidden_license",
                    "package": package.name,
                    "version": package.version,
                    "license": package.normalized_license,
                    "matched_pattern": pattern,
                }
            )

    return {
        "schema": "md-converters.supply-chain-report.v1",
        "generated_by": "tools/supply_chain_report.py",
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "policy": {
            "forbidden_license_patterns": list(forbidden_patterns),
            "fail_on_forbidden": fail_on_forbidden,
            "unknown_license_policy": "report_only",
        },
        "summary": {
            "packages": len(packages),
            "unknown_licenses": unknown_licenses,
            "forbidden_matches": len(issues),
        },
        "packages": [
            {
                "name": package.name,
                "version": package.version,
                "license": package.normalized_license,
                "license_expression": package.license_expression,
                "license_text": package.license_text,
                "license_classifiers": list(package.license_classifiers),
                "summary": package.summary,
                "home_page": package.home_page,
            }
            for package in packages
        ],
        "issues": issues,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a JSON license inventory for the current Python "
            "environment and optionally fail on forbidden license patterns."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("supply-chain-licenses.json"),
        help="JSON report path.",
    )
    parser.add_argument(
        "--fail-on-forbidden",
        action="store_true",
        help="Exit with code 1 when a forbidden license pattern is found.",
    )
    parser.add_argument(
        "--forbidden-license",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Additional forbidden license token or phrase.",
    )
    parser.add_argument(
        "--exclude-package",
        action="append",
        default=[],
        metavar="NAME",
        help="Exclude a package from the report; repeatable.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    forbidden_patterns = tuple(
        dict.fromkeys(
            [
                *DEFAULT_FORBIDDEN_LICENSE_PATTERNS,
                *args.forbidden_license,
            ]
        )
    )
    excluded = BOOTSTRAP_PACKAGES | set(args.exclude_package)
    packages = collect_packages(exclude=excluded)
    report = build_report(
        packages,
        forbidden_patterns=forbidden_patterns,
        fail_on_forbidden=args.fail_on_forbidden,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = report["summary"]
    print(
        "Supply-chain license report: "
        f"{summary['packages']} packages, "
        f"{summary['unknown_licenses']} unknown, "
        f"{summary['forbidden_matches']} forbidden match(es)."
    )
    print(f"Written: {args.output}")

    if args.fail_on_forbidden and report["issues"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
