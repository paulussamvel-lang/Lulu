from pathlib import Path

import pytest

from src.branding import WORKSPACE_APP, WORKSPACE_RELEASES
from src.core.agent_entry.standalone_paths import installed_app
from src.core.agent_entry.standalone_source import DESCRIPTOR
from src.core.updater.manifest import is_safe_manual_url


def test_workspace_path_is_independent_and_requires_install_descriptor(tmp_path, monkeypatch):
    home = tmp_path.resolve()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    app = home / "Applications" / WORKSPACE_APP
    descriptor = app / DESCRIPTOR
    descriptor.parent.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="INSTALLATION_TARGET_AUTHORITY_REQUIRED"):
        installed_app(app)

    descriptor.write_text("{}")
    assert installed_app(app) == app
    assert not (app.parent / "Lulu.app").exists()
    misplaced = home / WORKSPACE_APP
    app.rename(misplaced)
    with pytest.raises(RuntimeError, match="INSTALLATION_TARGET_AUTHORITY_REQUIRED"):
        installed_app(misplaced)


def test_workspace_release_page_has_a_closed_allowlist():
    assert is_safe_manual_url(WORKSPACE_RELEASES)
    assert not is_safe_manual_url(WORKSPACE_RELEASES + "/../settings")
