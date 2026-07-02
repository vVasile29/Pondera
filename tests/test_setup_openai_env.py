from scripts.setup_openai_env import run


def test_setup_openai_env_preserves_values_and_hides_key(tmp_path, capsys):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    secret_dir = home / ".openapi"
    repo.mkdir()
    secret_dir.mkdir(parents=True)
    (secret_dir / "secret_key").write_text("sk-test-secret\n", encoding="utf-8")
    (repo / ".gitignore").write_text("*.db\n", encoding="utf-8")
    (repo / ".env").write_text("# comment\nWEB_PORT=8080\nAI_ENABLED=false\n", encoding="utf-8")

    assert run(repo, home) == 0
    out = capsys.readouterr().out
    assert "sk-test-secret" not in out
    env = (repo / ".env").read_text(encoding="utf-8")
    assert "# comment" in env
    assert "WEB_PORT=8080" in env
    assert "OPENAI_API_KEY=sk-test-secret" in env
    assert "OPENAI_MODEL=gpt-4.1-mini" in env
    assert "AI_ENABLED=true" in env
    assert ".env" in (repo / ".gitignore").read_text(encoding="utf-8")


def test_setup_openai_env_missing_secret_fails_gracefully(tmp_path, capsys):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    repo.mkdir()
    home.mkdir()

    assert run(repo, home) == 1
    out = capsys.readouterr().out
    assert "not found" in out
    assert not (repo / ".env").exists()
