from __future__ import annotations

from collections.abc import Iterable

from alembic.script import ScriptDirectory
from alembic.script.revision import RevisionError
from alembic.util.exc import CommandError


def _normalized(values: Iterable[object]) -> set[str]:
    return {str(value).strip() for value in values if str(value).strip()}


def require_upgradeable_revisions(
    scripts: ScriptDirectory, observed_values: Iterable[object]
) -> None:
    """Accept one known current revision that can advance to the sole candidate head."""

    observed = _normalized(observed_values)
    heads = _normalized(scripts.get_heads())
    if len(observed) != 1:
        raise ValueError("database must expose exactly one Alembic revision")
    if len(heads) != 1:
        raise ValueError("candidate migration graph must expose exactly one head")

    current = next(iter(observed))
    head = next(iter(heads))
    try:
        scripts.get_revision(current)
        reachable = {
            revision.revision
            for revision in scripts.iterate_revisions(head, "base")
            if revision.revision
        }
    except (CommandError, RevisionError) as exc:
        raise ValueError("database revision is unknown to the candidate graph") from exc
    if current not in reachable:
        raise ValueError("database revision is not an ancestor of the candidate head")


def require_exact_candidate_heads(
    scripts: ScriptDirectory, observed_values: Iterable[object]
) -> None:
    observed = _normalized(observed_values)
    heads = _normalized(scripts.get_heads())
    if not observed or len(heads) != 1 or observed != heads:
        raise ValueError("database does not match the exact candidate Alembic head")
