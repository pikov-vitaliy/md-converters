from tools.supply_chain_report import PackageLicense, forbidden_matches


def _package(license_text: str) -> PackageLicense:
    return PackageLicense(
        name="demo",
        version="1.0.0",
        license_expression="",
        license_text=license_text,
        license_classifiers=(),
        summary="",
        home_page="",
    )


def _package_with_classifier(
    license_text: str,
    classifier: str,
) -> PackageLicense:
    return PackageLicense(
        name="demo",
        version="1.0.0",
        license_expression="",
        license_text=license_text,
        license_classifiers=(classifier,),
        summary="",
        home_page="",
    )


def test_forbidden_license_detects_strong_copyleft_token():
    matches = forbidden_matches(
        _package("GNU General Public License v3"),
        ("gpl",),
    )

    assert matches == ["gpl"]


def test_forbidden_license_does_not_match_apache():
    matches = forbidden_matches(
        _package("Apache Software License 2.0"),
        ("gpl", "agpl", "sspl"),
    )

    assert matches == []


def test_forbidden_license_ignores_long_notice_text_when_classifier_is_safe():
    notice = (
        "BSD 3-Clause License Copyright (c) 2026 Example. "
        "Permission is hereby granted under permissive terms. "
        "Historical bundled notices may mention the GNU General Public "
        "License without changing the package license."
    )

    matches = forbidden_matches(
        _package_with_classifier(notice, "OSI Approved :: BSD License"),
        ("gpl",),
    )

    assert matches == []


def test_forbidden_license_uses_long_text_when_no_authoritative_field_exists():
    notice = (
        "Copyright (c) 2026 Example. "
        "This package is distributed under the GNU General Public "
        "License version 3 with the full license body included below. "
        "Permission is intentionally governed by that copyleft license."
    )

    matches = forbidden_matches(
        _package(notice),
        ("gpl",),
    )

    assert matches == ["gpl"]
