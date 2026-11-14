"""Thin wrapper around the npm AgentCore CLI (`@aws/agentcore`).  (Do not modify.)

    stage_code()            copy the app into build/runtime/<project>/app/novamart/
    configure_runtime(...)  write the runtime entry in agentcore/agentcore.json
    deploy()                run `agentcore deploy --yes` (CDK -> CloudFormation)
    deployed_runtime_arn()  read the runtime ARN after deployment

Install the CLI once:  npm install -g @aws/agentcore
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(ROOT))

import boto3  # noqa: E402

import config  # noqa: E402

BUILD_DIR = ROOT / "build" / "runtime"
PROJECT_DIR = BUILD_DIR / config.RUNTIME_PROJECT_NAME
CODE_DIR = PROJECT_DIR / "app" / "novamart"
AGENTCORE_DIR = PROJECT_DIR / "agentcore"
ENTRYPOINT = "agent_orchestrator.py"

RUNTIME_FILES = [
    SRC / "agent_orchestrator.py",
    SRC / "agent_utils.py",
    SRC / "agent_observability.py",
    SRC / "bedrock_kb_retrieval.py",
    ROOT / "config.py",
]
RUNTIME_REQUIREMENTS = [
    "boto3>=1.40.0",
    "strands-agents>=1.10.0",
    "bedrock-agentcore>=1.0.0",
    "python-dotenv>=1.0.0",
]
_ARN_RE = re.compile(r"arn:aws[a-z-]*:bedrock-agentcore:[a-z0-9-]+:\d{12}:runtime/[A-Za-z0-9_-]+")


def _cli() -> str:
    """Locate the npm AgentCore CLI, skipping the legacy Python starter-toolkit `agentcore`."""
    if os.getenv("AGENTCORE_CLI"):
        return os.environ["AGENTCORE_CLI"]
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(folder) / "agentcore"
        if not (candidate.is_file() and os.access(candidate, os.X_OK)):
            continue
        try:
            with open(candidate, "rb") as fh:
                first_line = fh.readline()
        except OSError:
            continue
        if b"python" not in first_line:  # starter toolkit installs a Python entry-point script
            return str(candidate)
    raise RuntimeError("npm AgentCore CLI not found. Install it with: npm install -g @aws/agentcore "
                       "(or set AGENTCORE_CLI=/path/to/agentcore)")


def _run(args: list[str], cwd: Path) -> str:
    print(f"$ agentcore {' '.join(args)}   (cwd={cwd.relative_to(ROOT)})")
    env = {**os.environ, "AWS_REGION": config.AWS_REGION, "AWS_DEFAULT_REGION": config.AWS_REGION}
    proc = subprocess.run([_cli(), *args], cwd=cwd, env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(proc.stdout[-4000:])
    if proc.returncode != 0:
        raise RuntimeError(f"agentcore {args[0]} failed with exit code {proc.returncode}")
    return proc.stdout


def stage_code() -> Path:
    """Create the CLI project (first run only) and copy the application code into it."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    if not (AGENTCORE_DIR / "agentcore.json").exists():
        _run(["create", "--project-name", config.RUNTIME_PROJECT_NAME, "--no-agent", "--skip-git",
              "--skip-install"], cwd=BUILD_DIR)
    cdk_dir = AGENTCORE_DIR / "cdk"
    if not (cdk_dir / "node_modules").exists() and os.getenv("NOVAMART_SKIP_NPM") != "1":
        # Honours NPM_CONFIG_REGISTRY, e.g. https://registry.npmjs.org/ behind a private registry
        print(f"$ npm install   (cwd={cdk_dir.relative_to(ROOT)})")
        proc = subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=cdk_dir, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if proc.returncode != 0:
            print(proc.stdout[-2000:])
            raise RuntimeError("npm install of the AgentCore CDK project failed - see README "
                               "Troubleshooting (NPM_CONFIG_REGISTRY)")
    if CODE_DIR.exists():
        shutil.rmtree(CODE_DIR)
    CODE_DIR.mkdir(parents=True)
    for f in RUNTIME_FILES:
        shutil.copy2(f, CODE_DIR / f.name)
    (CODE_DIR / "requirements.txt").write_text("\n".join(RUNTIME_REQUIREMENTS) + "\n")
    (CODE_DIR / "pyproject.toml").write_text(
        "[project]\n"
        'name = "novamart-orchestrator"\n'
        'version = "1.0.0"\n'
        'requires-python = ">=3.12"\n'
        "dependencies = [\n" + "".join(f'    "{r}",\n' for r in RUNTIME_REQUIREMENTS) + "]\n"
    )
    print(f"Staged {len(RUNTIME_FILES)} files -> {CODE_DIR.relative_to(ROOT)}")
    return CODE_DIR


def configure_runtime(env_vars: dict[str, str], network_mode: str = "PUBLIC",
                      protocol: str = "HTTP", execution_role_arn: str | None = None) -> dict:
    """Write/replace the runtime definition in agentcore.json and the deployment target."""
    spec_path = AGENTCORE_DIR / "agentcore.json"
    spec = json.loads(spec_path.read_text())
    runtime = {
        "name": config.RUNTIME_AGENT_NAME,
        "description": "NovaMart multi-agent customer support (Orchestrator -> Workers)",
        "build": "CodeZip",
        "entrypoint": ENTRYPOINT,
        "codeLocation": "app/novamart/",
        "runtimeVersion": "PYTHON_3_12",
        "networkMode": network_mode,
        "protocol": protocol,
        "envVars": [{"name": k, "value": str(v)} for k, v in env_vars.items()],
    }
    if execution_role_arn:
        runtime["executionRoleArn"] = execution_role_arn
    spec["runtimes"] = [r for r in spec.get("runtimes", []) if r["name"] != runtime["name"]] + [runtime]
    spec_path.write_text(json.dumps(spec, indent=2) + "\n")

    account = boto3.client("sts", region_name=config.AWS_REGION).get_caller_identity()["Account"]
    targets = [{"name": "default", "description": "NovaMart project target",
                "account": account, "region": config.AWS_REGION}]
    (AGENTCORE_DIR / "aws-targets.json").write_text(json.dumps(targets, indent=2) + "\n")
    _run(["validate"], cwd=PROJECT_DIR)
    return runtime


def deploy() -> str:
    """Package and deploy via the CLI (CDK -> CloudFormation). Returns CLI output."""
    return _run(["deploy", "--yes"], cwd=PROJECT_DIR)


def deployed_runtime_arn() -> str:
    """Return the deployed runtime ARN (deployed-state.json, then the control-plane API)."""
    state_file = AGENTCORE_DIR / ".cli" / "deployed-state.json"
    if state_file.exists():
        matches = _ARN_RE.findall(state_file.read_text())
        matches = [m for m in matches if config.RUNTIME_AGENT_NAME in m] or matches
        if matches:
            return matches[0]
    ctrl = boto3.client("bedrock-agentcore-control", region_name=config.AWS_REGION)
    token = None
    while True:
        page = ctrl.list_agent_runtimes(**({"nextToken": token} if token else {}))
        for rt in page.get("agentRuntimes", []):
            if config.RUNTIME_AGENT_NAME in rt["agentRuntimeName"]:
                return rt["agentRuntimeArn"]
        token = page.get("nextToken")
        if not token:
            break
    raise RuntimeError("Runtime ARN not found - did `agentcore deploy` succeed?")
