from __future__ import annotations

from pathlib import Path

from app.dev.live_site_preflight import (
    SiteTarget,
    _parse_curl_write_out,
    cloud_addon_ready,
    evaluate_candidate,
    internal_identity_matches,
    render_markdown,
)


def _target() -> SiteTarget:
    return SiteTarget("site", "http://example.local/", Path("/tmp/example"))


def _wp_summary(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": True,
        "siteurl": "http://example.local",
        "home": "http://example.local",
        "blogname": "Example",
        "db_name": "local",
        "table_prefix": "wp_",
        "wp_version": "7.0",
        "active_theme": "twentytwentyfive 1.5",
        "active_plugins": ["npcink-cloud-addon/npcink-cloud-addon.php"],
        "counts": {"publish_post_page": 25},
        "cloud_settings": {
            "base_url": "https://cloud.example.com",
            "site_id": "site_example",
            "key_id_present": True,
            "secret_present": False,
            "api_key_present": False,
            "verified": True,
        },
        "sample_public_titles": ["Hello"],
    }
    payload.update(overrides)
    return payload


def test_internal_identity_matches_siteurl_and_home_hosts() -> None:
    assert internal_identity_matches(_target(), _wp_summary()) is True

    assert (
        internal_identity_matches(
            _target(),
            _wp_summary(siteurl="http://other.local", home="http://example.local"),
        )
        is False
    )


def test_parse_curl_write_out_returns_status_and_final_url() -> None:
    assert _parse_curl_write_out("200\nhttp://example.local/", fallback_url="x") == (
        200,
        "http://example.local/",
    )
    assert _parse_curl_write_out("", fallback_url="http://fallback.local/") == (
        0,
        "http://fallback.local/",
    )


def test_cloud_addon_ready_requires_verified_identity_and_key_presence() -> None:
    assert cloud_addon_ready(_wp_summary()) is True

    assert (
        cloud_addon_ready(
            _wp_summary(
                cloud_settings={
                    "base_url": "https://cloud.example.com",
                    "site_id": "site_example",
                    "key_id_present": False,
                    "secret_present": False,
                    "api_key_present": False,
                    "verified": True,
                }
            )
        )
        is False
    )


def test_evaluate_candidate_blocks_mismatched_small_unverified_site() -> None:
    evaluation = evaluate_candidate(
        target=_target(),
        http_summary={"ok": True, "status": 200},
        wp_summary=_wp_summary(
            siteurl="http://magick-device-manage.local",
            home="http://magick-device-manage.local",
            counts={"publish_post_page": 2},
            cloud_settings={"verified": False},
            active_plugins=["npcink-abilities-toolkit/npcink-abilities-toolkit.php"],
        ),
        min_public_items=10,
    )

    assert evaluation["decision"] == "no-go"
    assert evaluation["blockers"] == [
        "wordpress_identity_mismatch",
        "content_set_too_small",
        "cloud_addon_unverified",
    ]
    assert evaluation["warnings"] == ["cloud_addon_plugin_not_active"]


def test_render_markdown_keeps_cloud_secret_values_out_of_report() -> None:
    report = {
        "generated_at": "2026-06-20T00:00:00+00:00",
        "overall_decision": "go",
        "sites": [
            {
                "label": "site",
                "url": "http://example.local/",
                "path": "/tmp/example",
                "http": {"status": 200, "title": "Example"},
                "wordpress": _wp_summary(
                    cloud_settings={
                        "base_url": "https://cloud.example.com",
                        "site_id": "site_example",
                        "key_id_present": True,
                        "secret_present": True,
                        "api_key_present": True,
                        "verified": True,
                    }
                ),
                "sql_dump": {"exists": True, "bytes": 100, "pattern_count": 5},
                "evaluation": {"decision": "go", "blockers": [], "warnings": []},
            }
        ],
    }

    markdown = render_markdown(report)

    assert "secret_present" not in markdown
    assert "api_key_present" not in markdown
    assert "verified" in markdown
