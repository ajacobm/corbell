"""Infrastructure-as-code resource scanner.

Parses infra repos (Terraform, AWS CDK, Azure CDK, GCP CDK / CDKTF) and
returns a list of discovered resources as ``DataStoreNode`` / ``QueueNode``
objects ready to be upserted into the graph store.

Provider-specific patterns live in ``corbell.core.graph.providers.*`` so
each cloud's rules stay independent and easy to extend.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from corbell.core.graph.schema import DataStoreNode, QueueNode
from corbell.core.graph.providers import aws_patterns, azure_patterns, gcp_patterns

# Merge all TF resource maps from every cloud provider
_ALL_TF_RESOURCE_MAP: Dict[str, Tuple[str, str]] = {
    **aws_patterns.TF_RESOURCE_MAP,
    **azure_patterns.TF_RESOURCE_MAP,
    **gcp_patterns.TF_RESOURCE_MAP,
}

# Merge all CDK substring patterns from every cloud provider
_ALL_CDK_PATTERNS: List[Tuple[str, str, str]] = (
    aws_patterns.CDK_PATTERNS
    + azure_patterns.CDK_PATTERNS
    + gcp_patterns.CDK_PATTERNS
)

# Regex to parse Terraform resource blocks:
#   resource "aws_db_instance" "my_prod_db" {
_TF_RESOURCE_RE = re.compile(
    r'resource\s+"([^"]+)"\s+"([^"]+)"',
    re.MULTILINE,
)

CloudResource = Union[DataStoreNode, QueueNode]


def _make_node(
    resource_name: str,
    node_class: str,
    kind: str,
    infra_svc_id: str,
) -> CloudResource:
    """Create a DataStoreNode or QueueNode with a canonical ID."""
    slug = re.sub(r"[^a-z0-9_-]", "-", resource_name.lower()).strip("-")
    node_id = f"{node_class}:{kind}:{slug}"
    if node_class == "queue":
        return QueueNode(id=node_id, kind=kind, name=resource_name)
    return DataStoreNode(id=node_id, kind=kind, name=resource_name)


class InfraScanner:
    """Scans infrastructure-as-code repos and returns discovered cloud resources.

    Supports:
    - **Terraform** (``.tf``) — all three providers (AWS, Azure, GCP).
    - **CDK / CDKTF** (``.ts``, ``.py``) — pattern-matched constructor calls.
    """

    def scan(
        self,
        repo_path: Path,
        infra_svc_id: str,
    ) -> List[CloudResource]:
        """Scan *repo_path* and return all discovered cloud resource nodes.

        Args:
            repo_path: Root directory of the infrastructure repository.
            infra_svc_id: The service ID of the infra stack (used only for
                logging / future metadata; not stored on the node itself).

        Returns:
            List of :class:`DataStoreNode` and :class:`QueueNode` objects.
        """
        results: List[CloudResource] = []
        seen_ids: set[str] = set()

        for fp in repo_path.rglob("*"):
            if not fp.is_file():
                continue
            if any(part in {".git", "node_modules", "__pycache__", ".terraform"} for part in fp.parts):
                continue

            suffix = fp.suffix.lower()
            if suffix == ".tf":
                results.extend(self._scan_tf(fp, infra_svc_id, seen_ids))
            elif suffix in (".ts", ".py", ".js"):
                results.extend(self._scan_cdk(fp, infra_svc_id, seen_ids))

        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read(self, fp: Path) -> str:
        try:
            return fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    def _scan_tf(
        self,
        fp: Path,
        infra_svc_id: str,
        seen_ids: set,
    ) -> List[CloudResource]:
        """Parse a Terraform file and return matched resource nodes."""
        content = self._read(fp)
        found: List[CloudResource] = []
        for resource_type, resource_name in _TF_RESOURCE_RE.findall(content):
            entry = _ALL_TF_RESOURCE_MAP.get(resource_type)
            if entry is None:
                continue
            node_class, kind = entry
            node = _make_node(resource_name, node_class, kind, infra_svc_id)
            if node.id not in seen_ids:
                seen_ids.add(node.id)
                found.append(node)
        return found

    def _scan_cdk(
        self,
        fp: Path,
        infra_svc_id: str,
        seen_ids: set,
    ) -> List[CloudResource]:
        """Scan a TypeScript/Python CDK file.  Uses substring matching for
        speed; a name is extracted from the nearest string literal."""
        content = self._read(fp)
        found: List[CloudResource] = []

        for pattern, node_class, kind in _ALL_CDK_PATTERNS:
            start = 0
            while True:
                idx = content.find(pattern, start)
                if idx == -1:
                    break
                # Try to extract a resource name from the next quoted string
                window = content[idx: idx + 200]
                name_match = re.search(r'["\']([a-zA-Z0-9_\-]+)["\']', window)
                resource_name = name_match.group(1) if name_match else fp.stem
                node = _make_node(resource_name, node_class, kind, infra_svc_id)
                if node.id not in seen_ids:
                    seen_ids.add(node.id)
                    found.append(node)
                start = idx + len(pattern)

        return found
