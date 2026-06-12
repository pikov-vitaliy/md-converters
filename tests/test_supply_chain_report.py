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
