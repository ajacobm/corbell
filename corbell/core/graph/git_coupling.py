"""Git change coupling analyzer.

Walks git history to find files that frequently change together.
High co-change coupling is a strong signal of hidden dependencies —
files that should be changed together even if the code doesn't have
an explicit import/call between them.

Usage::

    from corbell.core.graph.git_coupling import GitCouplingAnalyzer
    from corbell.core.graph.sqlite_store import SQLiteGraphStore

    store = SQLiteGraphStore("path/to/db")
    analyzer = GitCouplingAnalyzer()
    edges_added = analyzer.build_coupling_edges("my-service", repo_path, store)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from corbell.core.graph.schema import DependencyEdge, GraphStore

logger = logging.getLogger(__name__)

_SKIP_PATHS: Set[str] = {
    "node_modules", ".git", "__pycache__", "venv", ".venv", "env",
    "dist", "build", "coverage", ".pytest_cache", ".tox",
}


class GitCouplingAnalyzer:
    """Compute file-level co-change coupling from git history.

    For each pair of files (A, B) that changed together in ≥3 commits,
    computes:

        coupling_strength = co_changes(A, B) / max(changes(A), changes(B))

    Pairs with ``coupling_strength >= threshold`` are stored as
    :class:`~corbell.core.graph.schema.DependencyEdge` with ``kind="git_coupling"``.
    """

    def __init__(
        self,
        months: int = 6,
        min_co_changes: int = 3,
        threshold: float = 0.30,
    ):
        """
        Args:
            months: How far back in history to look.
            min_co_changes: Minimum times two files must co-change to be included.
            threshold: Minimum coupling strength (0.0–1.0) to emit an edge.
        """
        self.months = months
        self.min_co_changes = min_co_changes
        self.threshold = threshold

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def compute_coupling(
        self, repo_path: Path
    ) -> Dict[Tuple[str, str], float]:
        """Walk git history and return file pair → coupling strength.

        Returns an empty dict if gitpython is unavailable or the repo has
        no git history.

        Args:
            repo_path: Root directory of a git-tracked repository.

        Returns:
            Dict mapping ``(file_a, file_b)`` tuples (lexicographically ordered)
            to their coupling strength in the range ``[threshold, 1.0]``.
        """
        try:
            from git import InvalidGitRepositoryError, Repo
        except ImportError:
            logger.debug(
                "gitpython not installed — skipping git coupling analysis. "
                "Install with: pip install gitpython"
            )
            return {}

        try:
            repo = Repo(str(repo_path), search_parent_directories=True)
        except Exception:
            logger.debug("Not a git repo or cannot open: %s", repo_path)
            return {}

        since = datetime.now() - timedelta(days=self.months * 30)

        file_changes: Dict[str, int] = defaultdict(int)
        co_changes: Dict[Tuple[str, str], int] = defaultdict(int)

        try:
            commits = list(repo.iter_commits(since=since.strftime("%Y-%m-%d")))
        except Exception as exc:
            logger.debug("Failed to iterate commits: %s", exc)
            return {}

        for commit in commits:
            if not commit.parents:
                continue  # skip root commit — diff against empty tree skews stats

            changed: Set[str] = set()
            try:
                for diff in commit.diff(commit.parents[0]):
                    for path_attr in ("a_path", "b_path"):
                        p = getattr(diff, path_attr, None)
                        if p and not self._should_skip_path(p):
                            changed.add(p)
            except Exception:
                continue

            changed_list = sorted(changed)
            for f in changed_list:
                file_changes[f] += 1

            for i, a in enumerate(changed_list):
                for b in changed_list[i + 1 :]:
                    key = (a, b)  # already sorted lexicographically
                    co_changes[key] += 1

        result: Dict[Tuple[str, str], float] = {}
        for (a, b), count in co_changes.items():
            if count < self.min_co_changes:
                continue
            max_changes = max(file_changes.get(a, 1), file_changes.get(b, 1))
            strength = count / max_changes
            if strength >= self.threshold:
                result[(a, b)] = round(strength, 4)

        logger.debug(
            "Git coupling: analyzed %d commits, found %d coupled pairs",
            len(commits),
            len(result),
        )
        return result

    def build_coupling_edges(
        self,
        service_id: str,
        repo_path: Path,
        store: GraphStore,
    ) -> int:
        """Run coupling analysis and store edges in the graph.

        Stores a ``DependencyEdge`` with ``kind="git_coupling"`` between
        the service node and itself (annotated with the file pair), since
        individual file nodes don't exist at the service-graph level.
        The metadata contains the coupled file paths and strength value,
        which Linear task export can use to flag co-change risk.

        Args:
            service_id: ID of the owning service.
            repo_path: Root of the repository to analyze.
            store: Graph store to write edges into.

        Returns:
            Number of coupling edges added.
        """
        coupled = self.compute_coupling(repo_path)
        if not coupled:
            return 0

        added = 0
        for (file_a, file_b), strength in coupled.items():
            store.upsert_edge(
                DependencyEdge(
                    source_id=service_id,
                    target_id=service_id,
                    kind="git_coupling",
                    metadata={
                        "file_a": file_a,
                        "file_b": file_b,
                        "strength": strength,
                        "note": (
                            f"{file_a} and {file_b} co-change {strength:.0%} of the time — "
                            "consider updating both when modifying either."
                        ),
                    },
                )
            )
            added += 1

        return added

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _should_skip_path(self, path: str) -> bool:
        parts = path.split("/")
        return any(part in _SKIP_PATHS for part in parts)

    def get_coupling_summary(
        self, repo_path: Path, top_n: int = 20
    ) -> List[Dict]:
        """Return the top-N coupled file pairs as a list of dicts.

        Useful for displaying coupling information in design documents
        before edges are written to the store.
        """
        coupled = self.compute_coupling(repo_path)
        sorted_pairs = sorted(coupled.items(), key=lambda x: x[1], reverse=True)
        return [
            {
                "file_a": a,
                "file_b": b,
                "strength": strength,
                "label": f"{int(strength * 100)}% coupled",
            }
            for (a, b), strength in sorted_pairs[:top_n]
        ]
