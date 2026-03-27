"""Cloud provider pattern modules for infrastructure scanning.

Each sub-module exposes:
- ``TF_RESOURCE_MAP``: mapping of Terraform resource type → (node_class, kind).
- ``CDK_PATTERNS``: list of (regex, node_class, kind) tuples for CDK/Python detection.
"""
