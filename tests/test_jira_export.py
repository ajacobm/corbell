"""Tests for the Jira exporter and CLI command."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from corbell.core.export.jira import JiraExporter


# ─── Fixtures ─────────────────────────────────────────────────────────────────

VALID_CREDS = dict(
    url="https://mycompany.atlassian.net",
    email="eng@mycompany.com",
    api_token="ATATT3xFfGF0abc123",
    project_key="ENG",
)


@pytest.fixture
def tasks_yaml(tmp_path) -> Path:
    """Write a minimal .tasks.yaml for testing."""
    data = {
        "title": "Payment Retry",
        "tracks": [
            {
                "name": "Backend",
                "tasks": [
                    {
                        "title": "Add retry queue",
                        "description": "Implement exponential backoff retry logic.",
                        "files_affected": ["payments/retry.py", "payments/queue.py"],
                    },
                    {
                        "title": "Update DB schema",
                        "description": "Add retry_count column to transactions table.",
                        "files_affected": ["migrations/0042_retry.sql"],
                    },
                ],
            },
            {
                "name": "Frontend",
                "tasks": [
                    {
                        "title": "Show retry status",
                        "description": "Display retry badge on payment history screen.",
                        "files_affected": [],
                    },
                ],
            },
        ],
    }
    path = tmp_path / "payment-retry.tasks.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


@pytest.fixture
def tasks_yaml_no_files(tmp_path) -> Path:
    """Tasks YAML with no files_affected."""
    data = {
        "title": "Simple Feature",
        "tracks": [
            {
                "name": "Track A",
                "tasks": [{"title": "Do thing", "description": ""}],
            }
        ],
    }
    path = tmp_path / "simple.tasks.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


def _mock_response(key: str = "ENG-1") -> MagicMock:
    resp = MagicMock()
    resp.status_code = 201
    resp.json.return_value = {"key": key, "id": "10001"}
    resp.raise_for_status.return_value = None
    return resp


# ─── Credential validation ────────────────────────────────────────────────────

def test_missing_url_raises():
    exporter = JiraExporter(email="a@b.com", api_token="tok", project_key="ENG")
    with pytest.raises(ValueError, match="url"):
        exporter.export_tasks("any.yaml")


def test_missing_email_raises():
    exporter = JiraExporter(url="https://x.atlassian.net", api_token="tok", project_key="ENG")
    with pytest.raises(ValueError, match="email"):
        exporter.export_tasks("any.yaml")


def test_missing_api_token_raises():
    exporter = JiraExporter(url="https://x.atlassian.net", email="a@b.com", project_key="ENG")
    with pytest.raises(ValueError, match="api_token"):
        exporter.export_tasks("any.yaml")


def test_missing_project_key_raises():
    exporter = JiraExporter(url="https://x.atlassian.net", email="a@b.com", api_token="tok")
    with pytest.raises(ValueError, match="project_key"):
        exporter.export_tasks("any.yaml")


def test_all_credentials_missing_lists_all():
    exporter = JiraExporter()
    with pytest.raises(ValueError) as exc_info:
        exporter.export_tasks("any.yaml")
    msg = str(exc_info.value)
    assert "url" in msg
    assert "email" in msg
    assert "api_token" in msg
    assert "project_key" in msg


# ─── Auth header ─────────────────────────────────────────────────────────────

def test_auth_header_is_basic():
    exporter = JiraExporter(**VALID_CREDS)
    headers = exporter._auth_headers()
    assert headers["Authorization"].startswith("Basic ")
    encoded = headers["Authorization"][len("Basic "):]
    decoded = base64.b64decode(encoded).decode()
    assert decoded == f"{VALID_CREDS['email']}:{VALID_CREDS['api_token']}"


# ─── Description builder ──────────────────────────────────────────────────────

def test_build_description_with_files():
    exporter = JiraExporter(**VALID_CREDS)
    task = {"description": "Do the thing.", "files_affected": ["a.py", "b.py"]}
    doc = exporter._build_description(task)
    assert doc["version"] == 1
    assert doc["type"] == "doc"
    # Flatten all text nodes across all paragraph content blocks
    texts = [
        item["text"]
        for node in doc["content"]
        if node["type"] == "paragraph"
        for item in node["content"]
        if item.get("text")
    ]
    assert any("Do the thing." in t for t in texts)
    assert any("a.py" in t for t in texts)


def test_build_description_no_files():
    exporter = JiraExporter(**VALID_CREDS)
    task = {"description": "Simple task.", "files_affected": []}
    doc = exporter._build_description(task)
    assert len(doc["content"]) == 1
    assert doc["content"][0]["content"][0]["text"] == "Simple task."


def test_build_description_empty_task():
    exporter = JiraExporter(**VALID_CREDS)
    doc = exporter._build_description({})
    # Should produce a non-empty doc with at least a blank paragraph
    assert doc["type"] == "doc"
    assert len(doc["content"]) >= 1


# ─── export_tasks — happy path ────────────────────────────────────────────────

def test_export_tasks_creates_one_issue_per_task(tasks_yaml):
    exporter = JiraExporter(**VALID_CREDS)

    responses = [_mock_response(f"ENG-{i}") for i in range(1, 4)]

    with patch("requests.Session.post", side_effect=responses):
        created = exporter.export_tasks(tasks_yaml)

    assert len(created) == 3


def test_export_tasks_issue_keys(tasks_yaml):
    exporter = JiraExporter(**VALID_CREDS)
    responses = [_mock_response(f"ENG-{i}") for i in range(1, 4)]

    with patch("requests.Session.post", side_effect=responses):
        created = exporter.export_tasks(tasks_yaml)

    keys = [c["issue_key"] for c in created]
    assert keys == ["ENG-1", "ENG-2", "ENG-3"]


def test_export_tasks_url_format(tasks_yaml):
    exporter = JiraExporter(**VALID_CREDS)
    responses = [_mock_response("ENG-7") for _ in range(3)]

    with patch("requests.Session.post", side_effect=responses):
        created = exporter.export_tasks(tasks_yaml)

    for issue in created:
        assert issue["url"] == "https://mycompany.atlassian.net/browse/ENG-7"


def test_export_tasks_title_prefix(tasks_yaml):
    exporter = JiraExporter(**VALID_CREDS)
    responses = [_mock_response(f"ENG-{i}") for i in range(1, 4)]

    captured_payloads = []

    original_post = MagicMock(side_effect=responses)

    def capture_post(url, data=None, **kwargs):
        captured_payloads.append(json.loads(data))
        return responses[len(captured_payloads) - 1]

    with patch("requests.Session.post", side_effect=capture_post):
        exporter.export_tasks(tasks_yaml)

    summaries = [p["fields"]["summary"] for p in captured_payloads]
    assert all(s.startswith("[Payment Retry]") for s in summaries)


def test_export_tasks_project_key_in_payload(tasks_yaml):
    exporter = JiraExporter(**VALID_CREDS)
    responses = [_mock_response(f"ENG-{i}") for i in range(1, 4)]

    captured = []

    def capture_post(url, data=None, **kwargs):
        captured.append(json.loads(data))
        return responses[len(captured) - 1]

    with patch("requests.Session.post", side_effect=capture_post):
        exporter.export_tasks(tasks_yaml)

    for payload in captured:
        assert payload["fields"]["project"]["key"] == "ENG"


def test_export_tasks_issue_type_in_payload(tasks_yaml):
    exporter = JiraExporter(**VALID_CREDS, issue_type="Story")
    responses = [_mock_response(f"ENG-{i}") for i in range(1, 4)]

    captured = []

    def capture_post(url, data=None, **kwargs):
        captured.append(json.loads(data))
        return responses[len(captured) - 1]

    with patch("requests.Session.post", side_effect=capture_post):
        exporter.export_tasks(tasks_yaml)

    for payload in captured:
        assert payload["fields"]["issuetype"]["name"] == "Story"


def test_export_tasks_api_endpoint(tasks_yaml):
    exporter = JiraExporter(**VALID_CREDS)
    responses = [_mock_response(f"ENG-{i}") for i in range(1, 4)]

    called_urls = []

    def capture_post(url, data=None, **kwargs):
        called_urls.append(url)
        return responses[len(called_urls) - 1]

    with patch("requests.Session.post", side_effect=capture_post):
        exporter.export_tasks(tasks_yaml)

    for url in called_urls:
        assert url == "https://mycompany.atlassian.net/rest/api/3/issue"


def test_export_tasks_no_files_affected(tasks_yaml_no_files):
    exporter = JiraExporter(**VALID_CREDS)
    responses = [_mock_response("ENG-1")]

    with patch("requests.Session.post", side_effect=responses):
        created = exporter.export_tasks(tasks_yaml_no_files)

    assert len(created) == 1
    assert created[0]["issue_key"] == "ENG-1"


def test_export_tasks_trailing_slash_stripped():
    """URL trailing slash must not produce double-slash in the API path."""
    exporter = JiraExporter(
        url="https://mycompany.atlassian.net/",  # trailing slash
        email="eng@mycompany.com",
        api_token="tok",
        project_key="ENG",
    )
    assert not exporter.url.endswith("/")


# ─── Missing requests package ─────────────────────────────────────────────────

def test_missing_requests_raises_import_error(tasks_yaml):
    exporter = JiraExporter(**VALID_CREDS)
    with patch.dict("sys.modules", {"requests": None}):
        with pytest.raises(ImportError, match="requests"):
            exporter.export_tasks(tasks_yaml)


# ─── Workspace config integration ────────────────────────────────────────────

def test_jira_integration_in_workspace(sample_workspace_yaml):
    from corbell.core.workspace import load_workspace

    cfg = load_workspace(sample_workspace_yaml)
    # JiraIntegration should exist with default values
    jira = cfg.integrations.jira
    assert hasattr(jira, "url")
    assert hasattr(jira, "email")
    assert hasattr(jira, "api_token")
    assert hasattr(jira, "project_key")
    assert jira.issue_type == "Task"


def test_jira_workspace_config_overrides_env(tmp_path):
    """Values in workspace.yaml should be picked up by the exporter."""
    from corbell.core.workspace import load_workspace

    ws_dir = tmp_path / "corbell-data"
    ws_dir.mkdir()
    ws_file = ws_dir / "workspace.yaml"
    ws_file.write_text(
        """\
version: "1"
integrations:
  jira:
    url: https://acme.atlassian.net
    email: dev@acme.com
    api_token: secret-token
    project_key: ACME
    issue_type: Story
""",
        encoding="utf-8",
    )
    cfg = load_workspace(ws_file)
    jira = cfg.integrations.jira
    assert jira.url == "https://acme.atlassian.net"
    assert jira.email == "dev@acme.com"
    assert jira.api_token == "secret-token"
    assert jira.project_key == "ACME"
    assert jira.issue_type == "Story"


# ─── Jira API error handling ──────────────────────────────────────────────────

def test_raise_for_status_surfaces_jira_error_messages():
    exporter = JiraExporter(**VALID_CREDS)
    resp = MagicMock()
    resp.status_code = 400
    resp.json.return_value = {
        "errorMessages": ["Project 'XYZ' does not exist."],
        "errors": {},
    }
    with pytest.raises(ValueError, match="Project 'XYZ' does not exist"):
        exporter._raise_for_status(resp)


def test_raise_for_status_surfaces_field_errors():
    exporter = JiraExporter(**VALID_CREDS)
    resp = MagicMock()
    resp.status_code = 400
    resp.json.return_value = {
        "errorMessages": [],
        "errors": {"issuetype": "Issue type is required."},
    }
    with pytest.raises(ValueError, match="issuetype"):
        exporter._raise_for_status(resp)


def test_raise_for_status_401_fallback_to_text():
    exporter = JiraExporter(**VALID_CREDS)
    resp = MagicMock()
    resp.status_code = 401
    resp.json.side_effect = Exception("not json")
    resp.text = "Unauthorized"
    with pytest.raises(ValueError, match="401"):
        exporter._raise_for_status(resp)


def test_raise_for_status_2xx_does_not_raise():
    exporter = JiraExporter(**VALID_CREDS)
    resp = MagicMock()
    resp.status_code = 201
    exporter._raise_for_status(resp)  # should not raise


def test_export_tasks_surfaces_jira_error(tasks_yaml):
    """HTTPError from Jira should surface as a clean ValueError, not a traceback."""
    exporter = JiraExporter(**VALID_CREDS)

    bad_resp = MagicMock()
    bad_resp.status_code = 400
    bad_resp.json.return_value = {"errorMessages": ["Issue type 'Task' not found."], "errors": {}}

    with patch("requests.Session.post", return_value=bad_resp):
        with pytest.raises(ValueError, match="Issue type 'Task' not found"):
            exporter.export_tasks(tasks_yaml)


# ─── CLI command ──────────────────────────────────────────────────────────────

def test_cli_export_jira_reads_config_from_workspace(tmp_path, tasks_yaml):
    """CLI `export jira` must pass workspace.yaml values to JiraExporter."""
    from typer.testing import CliRunner
    from corbell.cli.commands.export import app

    # Create a minimal workspace with Jira config
    ws_dir = tmp_path / "corbell-data"
    ws_dir.mkdir()
    (ws_dir / "workspace.yaml").write_text(
        """\
version: "1"
integrations:
  jira:
    url: https://test.atlassian.net
    email: test@test.com
    api_token: test-token
    project_key: TEST
    issue_type: Task
""",
        encoding="utf-8",
    )

    captured = {}

    def fake_export(self, path):
        captured["url"] = self.url
        captured["email"] = self.email
        captured["api_token"] = self.api_token
        captured["project_key"] = self.project_key
        return [{"issue_key": "TEST-1", "title": "t", "url": "u"}]

    runner = CliRunner()
    with patch("corbell.core.export.jira.JiraExporter.export_tasks", fake_export):
        result = runner.invoke(
            app,
            ["jira", str(tasks_yaml), "--workspace", str(tmp_path)],
        )

    assert result.exit_code == 0, result.output
    assert captured["url"] == "https://test.atlassian.net"
    assert captured["email"] == "test@test.com"
    assert captured["api_token"] == "test-token"
    assert captured["project_key"] == "TEST"


def test_cli_export_jira_shows_clean_error_on_bad_credentials(tmp_path, tasks_yaml):
    """CLI must show a clean error message, not a Python traceback."""
    from typer.testing import CliRunner
    from corbell.cli.commands.export import app

    ws_dir = tmp_path / "corbell-data"
    ws_dir.mkdir()
    (ws_dir / "workspace.yaml").write_text(
        """\
version: "1"
integrations:
  jira:
    url: https://test.atlassian.net
    email: test@test.com
    api_token: bad-token
    project_key: TEST
    issue_type: Task
""",
        encoding="utf-8",
    )

    def fake_export(self, path):
        raise ValueError("Jira API 401: Unauthorized")

    runner = CliRunner()
    with patch("corbell.core.export.jira.JiraExporter.export_tasks", fake_export):
        result = runner.invoke(
            app,
            ["jira", str(tasks_yaml), "--workspace", str(tmp_path)],
        )

    assert result.exit_code == 1
    assert "Jira API 401" in result.output
    assert "Traceback" not in result.output
