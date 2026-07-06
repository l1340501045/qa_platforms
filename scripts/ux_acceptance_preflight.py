"""UI/UX 真实验收前只读预检。

这个脚本只检查分支、工作区、验收资料、模型配置和基础服务状态，
不创建系统、不上传文档、不触发生成、不写数据库。
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_BRANCH = "feat/qa-platform-ux-modernization"
GENERATOR_BASE_REF = "checkpoint/architecture-migration-pre-ux...HEAD"
EXPECTED_ENV = {
    "LLM_PRIMARY_MODEL": "claude-opus-4-6",
    "LLM_VISION_MODEL": "claude-opus-4-6",
    "LLM_VERIFY_MODEL": "deepseek-v4-pro-office",
    "LLM_CONCURRENCY": "8",
}
EXPECTED_GENERATION_CONFIG = {
    "existence_merge_enabled": True,
    "split_cap_enabled": True,
    "cases_per_tp_cap": 4,
    "p0_quota_enabled": False,
}
ACCEPTANCE_FILES = [
    "docs/acceptance/README.md",
    "docs/acceptance/runbook.md",
    "docs/acceptance/evidence-ledger.md",
    "docs/acceptance/first-use-observation.md",
    "docs/acceptance/post-batch-report-template.md",
    "docs/acceptance/ux-small-batch-prd.md",
]


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    fix: str = ""


def _run(args: list[str], *, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _parse_frontend_generation_config(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    marker = "export const BEST_PRACTICE_GENERATION_CONFIG = {"
    start = text.index(marker)
    body = text[start : text.index("};", start)]
    parsed: dict[str, object] = {}
    for raw_line in body.splitlines()[1:]:
        line = raw_line.strip().rstrip(",")
        if not line:
            continue
        key, raw_value = line.split(":", 1)
        value = raw_value.strip()
        if value == "true":
            parsed[key] = True
        elif value == "false":
            parsed[key] = False
        elif value.startswith("'") and value.endswith("'"):
            parsed[key] = value.strip("'")
        else:
            parsed[key] = int(value) if value.isdigit() else float(value)
    return parsed


def _parse_pipeline_generation_config(path: Path) -> dict[str, object]:
    module = ast.parse(path.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "BEST_PRACTICE_GENERATION_CONFIG":
                value = ast.literal_eval(node.value)
                if isinstance(value, dict):
                    return value
    raise ValueError("未找到 BEST_PRACTICE_GENERATION_CONFIG")


def _parse_settings_generation_defaults(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    parsed: dict[str, object] = {}
    for key in EXPECTED_GENERATION_CONFIG:
        match = re.search(rf"^\s*{re.escape(key)}:\s*[^=]+=\s*(True|False|\d+)\s*$", text, re.MULTILINE)
        if not match:
            continue
        raw_value = match.group(1)
        if raw_value == "True":
            parsed[key] = True
        elif raw_value == "False":
            parsed[key] = False
        else:
            parsed[key] = int(raw_value)
    return parsed


def check_branch() -> CheckResult:
    result = _run(["git", "branch", "--show-current"])
    branch = result.stdout.strip()
    if branch == EXPECTED_BRANCH:
        return CheckResult("当前分支", True, branch)
    return CheckResult(
        "当前分支",
        False,
        branch or "无法读取当前分支",
        f"切换到 {EXPECTED_BRANCH} 后再跑真实验收。",
    )


def check_worktree(allow_dirty: bool) -> CheckResult:
    result = _run(["git", "status", "--short"])
    status = result.stdout.strip()
    if not status:
        return CheckResult("工作区状态", True, "干净")
    if allow_dirty:
        return CheckResult("工作区状态", True, "存在未提交改动，但已通过 --allow-dirty 放行")
    return CheckResult(
        "工作区状态",
        False,
        status.splitlines()[0],
        "先提交或处理未提交改动，避免真实验收结果无法追溯到固定代码版本。",
    )


def check_generator_diff() -> CheckResult:
    result = _run(
        [
            "git",
            "diff",
            GENERATOR_BASE_REF,
            "--name-only",
            "--",
            "src/testcase_generator",
        ]
    )
    if result.returncode != 0:
        return CheckResult(
            "生成核心 diff",
            False,
            (result.stderr or result.stdout).strip() or "git diff 执行失败",
            f"确认回退锚点 {GENERATOR_BASE_REF} 存在。",
        )
    changed = [line for line in result.stdout.splitlines() if line.strip()]
    if not changed:
        return CheckResult("生成核心 diff", True, "src/testcase_generator 无变更")
    return CheckResult(
        "生成核心 diff",
        False,
        ", ".join(changed[:5]),
        "UI/UX 验收分支不应混入生成核心变更；先拆分或确认这些变更属于其他任务。",
    )


def check_acceptance_files() -> CheckResult:
    missing = [path for path in ACCEPTANCE_FILES if not (ROOT / path).exists()]
    if not missing:
        return CheckResult("验收资料", True, "docs/acceptance 资料齐全")
    return CheckResult(
        "验收资料",
        False,
        "缺失: " + ", ".join(missing),
        "先补齐 README、runbook、证据台账、观察表、回填模板和小规模 PRD 样例。",
    )


def check_env() -> CheckResult:
    env_path = ROOT / ".env"
    values = _read_env_file(env_path)
    if not values:
        return CheckResult(
            ".env 配置",
            False,
            ".env 不存在或为空",
            "先按项目环境说明准备 .env，再确认 LLM 模型配置。",
        )
    mismatches = []
    for key, expected in EXPECTED_ENV.items():
        actual = values.get(key)
        if actual != expected:
            mismatches.append(f"{key}={actual or '<missing>'}，期望 {expected}")
    if not mismatches:
        return CheckResult(".env 配置", True, "真实跑批模型配置符合 runbook")
    return CheckResult(
        ".env 配置",
        False,
        "; ".join(mismatches),
        "按 docs/acceptance/runbook.md 第 2 节修正 LLM 配置。",
    )


def _generation_config_mismatches(name: str, actual: dict[str, object]) -> list[str]:
    mismatches = []
    for key, expected in EXPECTED_GENERATION_CONFIG.items():
        if key not in actual:
            mismatches.append(f"{name}.{key}=<missing>，期望 {expected}")
            continue
        if actual[key] != expected:
            mismatches.append(f"{name}.{key}={actual[key]}，期望 {expected}")
    return mismatches


def check_generation_config() -> CheckResult:
    try:
        configs = {
            "frontend": _parse_frontend_generation_config(ROOT / "web/src/services/batchApi.ts"),
            "pipeline": _parse_pipeline_generation_config(ROOT / "src/testcase_generator/pipeline/config.py"),
            "settings": _parse_settings_generation_defaults(ROOT / "src/platform_api/core/settings.py"),
        }
    except (OSError, ValueError, SyntaxError, KeyError) as exc:
        return CheckResult(
            "生成配置",
            False,
            str(exc),
            "确认 batchApi.ts、pipeline/config.py、settings.py 中的生成配置结构未漂移。",
        )

    mismatches: list[str] = []
    for name, actual in configs.items():
        mismatches.extend(_generation_config_mismatches(name, actual))
    if not mismatches:
        summary = ", ".join(f"{key}={value}" for key, value in EXPECTED_GENERATION_CONFIG.items())
        return CheckResult("生成配置", True, summary)
    return CheckResult(
        "生成配置",
        False,
        "; ".join(mismatches),
        "按 docs/acceptance/runbook.md 第 2 节修正真实跑批配置，保持前端、settings、pipeline 契约一致。",
    )


def _http_check(name: str, url: str, expected: str, *, include_body: bool = False) -> CheckResult:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=5) as response:
            status = response.status
            body = response.read(200).decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        return CheckResult(name, False, str(exc), expected)
    body_preview = " ".join(body.split())[:120] if include_body else ""
    detail = f"HTTP {status}" + (f" {body_preview}" if body_preview else "")
    if 200 <= status < 400:
        return CheckResult(name, True, detail)
    return CheckResult(name, False, detail, expected)


def check_worker() -> CheckResult:
    result = _run(
        [
            "uv",
            "run",
            "celery",
            "-A",
            "src.platform_api.core.celery_app.celery_app",
            "inspect",
            "ping",
            "--timeout=5",
        ],
        timeout=15,
    )
    combined = (result.stdout + result.stderr).strip()
    if result.returncode == 0 and "pong" in combined:
        return CheckResult("Worker", True, combined.splitlines()[0])
    return CheckResult(
        "Worker",
        False,
        combined or "celery inspect ping 无响应",
        "确认已运行 ./scripts/start_platform_services.sh，且 worker 能连接 Redis。",
    )


def run_checks(skip_runtime: bool, allow_dirty: bool) -> list[CheckResult]:
    checks = [
        check_branch(),
        check_worktree(allow_dirty),
        check_generator_diff(),
        check_acceptance_files(),
        check_env(),
        check_generation_config(),
    ]
    if not skip_runtime:
        checks.extend(
            [
                _http_check(
                    "API",
                    "http://127.0.0.1:8000/health",
                    "启动 API 后应返回健康状态。",
                    include_body=True,
                ),
                _http_check("Frontend", "http://127.0.0.1:3000", "启动 web dev server 后应返回页面。"),
                check_worker(),
            ]
        )
    return checks


def print_results(results: list[CheckResult], skip_runtime: bool) -> None:
    print("UI/UX 真实验收前预检")
    print("=" * 32)
    if skip_runtime:
        print("运行态检查：已跳过（--skip-runtime）")
        print("-" * 32)
    for item in results:
        mark = "PASS" if item.ok else "FAIL"
        print(f"[{mark}] {item.name}: {item.detail}")
        if not item.ok and item.fix:
            print(f"       处理建议: {item.fix}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UI/UX 真实验收前只读预检")
    parser.add_argument(
        "--skip-runtime",
        action="store_true",
        help="只做静态检查，跳过 API/frontend/worker 健康检查",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="允许工作区存在未提交改动，仅用于开发脚本时自检",
    )
    return parser.parse_args()


def main() -> int:
    os.chdir(ROOT)
    args = parse_args()
    results = run_checks(skip_runtime=args.skip_runtime, allow_dirty=args.allow_dirty)
    print_results(results, skip_runtime=args.skip_runtime)
    failed = [item for item in results if not item.ok]
    if failed:
        print("-" * 32)
        print(f"预检未通过：{len(failed)} 项需要处理。不要开始真实跑批。")
        return 1
    print("-" * 32)
    print("预检通过：可以继续按 runbook 执行真实小规模批次。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
