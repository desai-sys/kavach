#!/usr/bin/env python3
"""Copy the Kavach agent into a project created by the AgentCore CLI and wire it up.

Usage:
    python scripts/install_agent.py ../KavachAgent            # agent named Kavach
    python scripts/install_agent.py ../KavachAgent --agent Kavach

What it does:
  1. copies agent/ and every shared layers/common file (kavach_*.py and businesses.json) into
     <project>/app/<agent>/ (replacing the generated main.py),
  2. adds playwright to the agent's pyproject.toml (for AgentCore Browser),
  3. adds kavach-agent-policy.json and KAVACH_CONFIG_PARAM to the runtime in agentcore.json.
Then run `agentcore deploy` inside the project.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXTRA_DEPS = ['"playwright >= 1.42.0"', '"nest-asyncio >= 1.5.0"']


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path, help="Folder created by `agentcore create`")
    parser.add_argument("--agent", default="Kavach", help="Agent name used in `agentcore create --name`")
    args = parser.parse_args()

    project = args.project.resolve()
    app_dir = project / "app" / args.agent
    config_path = project / "agentcore" / "agentcore.json"
    if not app_dir.is_dir() or not config_path.is_file():
        sys.exit(f"Not an AgentCore project with agent '{args.agent}': {project}")

    # 1. code
    for item in (REPO / "agent").iterdir():
        if item.name == "__pycache__":
            continue
        target = app_dir / item.name
        if item.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(item, target, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(item, target)
    for shared in sorted((REPO / "layers" / "common").iterdir()):  # kavach_*.py modules and businesses.json
        if shared.suffix in (".py", ".json"):
            shutil.copy2(shared, app_dir / shared.name)
    print(f"Copied agent code into {app_dir}")

    # 2. dependencies
    pyproject = app_dir / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    missing = [d for d in EXTRA_DEPS if d.split()[0].strip('"') not in text]
    if missing:
        text = re.sub(r"dependencies\s*=\s*\[", lambda m: m.group(0) + "\n    " + ",\n    ".join(missing) + ",",
                      text, count=1)
        pyproject.write_text(text, encoding="utf-8")
        print(f"Added to pyproject.toml: {', '.join(missing)}")

    # 3. runtime config
    config = json.loads(config_path.read_text(encoding="utf-8"))
    runtime = next((r for r in config.get("runtimes", []) if r.get("name") == args.agent), None)
    if runtime is None:
        sys.exit(f"No runtime named {args.agent} in {config_path}")
    policies = runtime.setdefault("additionalPolicies", [])
    if "kavach-agent-policy.json" not in policies:
        policies.append("kavach-agent-policy.json")
    env = runtime.setdefault("envVars", [])
    if not any(e.get("name") == "KAVACH_CONFIG_PARAM" for e in env):
        env.append({"name": "KAVACH_CONFIG_PARAM", "value": "/kavach/config"})
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {config_path} (extra IAM policy + config env var)")

    print("\nNext: cd into the project, run `agentcore deploy`, then `agentcore status` to get the runtime ARN.")


if __name__ == "__main__":
    main()
