#!/usr/bin/env python3
"""Populate local .env OpenAI settings from ~/.openapi/secret_key."""

from pathlib import Path


def run(repo_root: Path, home: Path) -> int:
    secret_path = home / ".openapi" / "secret_key"
    env_path = repo_root / ".env"
    gitignore_path = repo_root / ".gitignore"

    if not secret_path.exists():
        print("OpenAI secret file not found at ~/.openapi/secret_key")
        return 1

    key = secret_path.read_text(encoding="utf-8").strip()
    if not key:
        print("OpenAI secret file is empty")
        return 1

    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    desired = {
        "OPENAI_API_KEY": key,
        "OPENAI_MODEL": "gpt-4.1-mini",
        "AI_ENABLED": "true",
    }
    seen = set()
    updated = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            updated.append(line)
            continue
        name = line.split("=", 1)[0].strip()
        if name in desired:
            updated.append(f"{name}={desired[name]}")
            seen.add(name)
        else:
            updated.append(line)
    for name, value in desired.items():
        if name not in seen:
            updated.append(f"{name}={value}")
    env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")

    if gitignore_path.exists():
        gitignore_lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        if ".env" not in {line.strip() for line in gitignore_lines}:
            gitignore_lines.append(".env")
            gitignore_path.write_text("\n".join(gitignore_lines) + "\n", encoding="utf-8")

    print("Updated .env OpenAI settings")
    return 0


def main() -> int:
    return run(Path(__file__).resolve().parents[1], Path.home())


if __name__ == "__main__":
    raise SystemExit(main())
