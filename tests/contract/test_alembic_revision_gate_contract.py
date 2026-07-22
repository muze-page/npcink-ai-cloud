from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from scripts.alembic_revision_gate import (
    require_exact_candidate_heads,
    require_upgradeable_revisions,
)


def _cloud_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _candidate_scripts() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(_cloud_root() / "alembic.ini")))


def _temporary_scripts(
    tmp_path: Path, revisions: list[tuple[str, str | tuple[str, ...] | None]]
) -> ScriptDirectory:
    script_root = tmp_path / "migrations"
    versions = script_root / "versions"
    versions.mkdir(parents=True)
    for revision, down_revision in revisions:
        (versions / f"{revision}.py").write_text(
            "\n".join(
                (
                    f'revision = "{revision}"',
                    f"down_revision = {down_revision!r}",
                    "branch_labels = None",
                    "depends_on = None",
                    "",
                )
            ),
            encoding="utf-8",
        )
    return ScriptDirectory(str(script_root))


def test_upgradeable_gate_accepts_exact_head_and_known_ancestor() -> None:
    scripts = _candidate_scripts()

    require_upgradeable_revisions(scripts, scripts.get_heads())
    require_upgradeable_revisions(scripts, {"20260312_0001"})


@pytest.mark.parametrize("observed", [set(), {"20260312_0001", "20260717_0068"}])
def test_upgradeable_gate_rejects_empty_or_split_database_revision(
    observed: set[str],
) -> None:
    with pytest.raises(ValueError, match="exactly one Alembic revision"):
        require_upgradeable_revisions(_candidate_scripts(), observed)


def test_upgradeable_gate_normalizes_unknown_revision_to_value_error() -> None:
    with pytest.raises(ValueError, match="unknown to the candidate graph"):
        require_upgradeable_revisions(_candidate_scripts(), {"bogus"})


def test_upgradeable_gate_rejects_candidate_graph_with_multiple_heads(tmp_path: Path) -> None:
    scripts = _temporary_scripts(
        tmp_path,
        [("base", None), ("left", "base"), ("right", "base")],
    )

    with pytest.raises(ValueError, match="exactly one head"):
        require_upgradeable_revisions(scripts, {"base"})


def test_upgradeable_gate_rejects_revision_not_ancestral_to_candidate_head(
    tmp_path: Path,
) -> None:
    scripts = _temporary_scripts(
        tmp_path,
        [
            ("old_base", None),
            ("old_head", "old_base"),
            ("candidate_base", None),
            ("candidate_head", "candidate_base"),
        ],
    )
    # Model a candidate whose selected head is on a different branch. The
    # database revision is known to the candidate graph but cannot reach it.
    scripts.get_heads = lambda: ["candidate_head"]  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="not an ancestor"):
        require_upgradeable_revisions(scripts, {"old_head"})


def test_exact_gate_accepts_only_the_single_candidate_head() -> None:
    scripts = _candidate_scripts()
    head = scripts.get_heads()[0]

    require_exact_candidate_heads(scripts, {head})
    with pytest.raises(ValueError, match="exact candidate Alembic head"):
        require_exact_candidate_heads(scripts, {"20260312_0001"})
    with pytest.raises(ValueError, match="exact candidate Alembic head"):
        require_exact_candidate_heads(scripts, set())
    with pytest.raises(ValueError, match="exact candidate Alembic head"):
        require_exact_candidate_heads(scripts, {head, "20260312_0001"})


def test_exact_gate_rejects_candidate_graph_with_multiple_heads(tmp_path: Path) -> None:
    scripts = _temporary_scripts(
        tmp_path,
        [("base", None), ("left", "base"), ("right", "base")],
    )

    with pytest.raises(ValueError, match="exact candidate Alembic head"):
        require_exact_candidate_heads(scripts, {"left", "right"})
