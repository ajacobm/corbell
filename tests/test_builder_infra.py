import tempfile
import json
from pathlib import Path
from corbell.core.graph.schema import GraphStore
from corbell.core.graph.sqlite_store import SQLiteGraphStore
from corbell.core.graph.builder import ServiceGraphBuilder

def test_builder_detects_infrastructure(tmp_path):
    # Setup mock workspace
    store = SQLiteGraphStore(str(tmp_path / "test.db"))
    builder = ServiceGraphBuilder(store)
    
    # 1. Create a normal service mock
    normal_service = tmp_path / "normal_service"
    normal_service.mkdir()
    (normal_service / "main.py").write_text("print('hello')")
    (normal_service / "package.json").write_text('{"name": "test"}')

    # 2. Create an infrastructure service mock (AWS CDK)
    cdk_service = tmp_path / "cdk_service"
    cdk_service.mkdir()
    (cdk_service / "stack.ts").write_text("import * as cdk from 'aws-cdk-lib';")
    (cdk_service / "package.json").write_text(json.dumps({
        "name": "my-infra",
        "dependencies": {
            "aws-cdk-lib": "^2.0.0"
        }
    }))
    
    # 3. Create an infrastructure service mock (CDKTF)
    cdktf_service = tmp_path / "cdktf_service"
    cdktf_service.mkdir()
    (cdktf_service / "main.ts").write_text("import { App } from 'cdktf';")
    (cdktf_service / "package.json").write_text(json.dumps({
        "name": "terraform-infra",
        "dependencies": {
            "cdktf": "^0.15.0"
        }
    }))

    services = [
        {"id": "normal-svc", "repo": str(normal_service), "language": "python"},
        {"id": "cdk-infra", "repo": str(cdk_service), "language": "typescript"},
        {"id": "cdktf-infra", "repo": str(cdktf_service), "language": "typescript"},
    ]

    builder.build_from_workspace(services)

    node_normal = store.get_service("normal-svc")
    assert node_normal is not None
    assert node_normal.service_type == "service"  # default fallback if not api/worker etc detected properly, or it might just be the default fallback in builder

    node_cdk = store.get_service("cdk-infra")
    assert node_cdk is not None
    assert node_cdk.service_type == "infrastructure"

    node_cdktf = store.get_service("cdktf-infra")
    assert node_cdktf is not None
    assert node_cdktf.service_type == "infrastructure"
