# -*- coding: utf-8 -*-
"""飞鹰CRM系统 · 一键测试门禁：单元 + 接口 + 端到端，产出 junit/XML/JSON 报告与执行摘要。

退出码非 0 即视为质量门禁不通过，阻断部署。
用法：python scripts/run_tests.py
"""
import io
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(ROOT, "reports")
os.makedirs(REPORTS, exist_ok=True)
os.makedirs(os.path.join(REPORTS, "screenshots"), exist_ok=True)

SUITES = [
    ("单元测试（业务内核纯函数）", "tests/test_unit_core.py"),
    ("接口测试（REST 全流程 + 集成能力）", "tests/test_api.py"),
    ("端到端测试（14 页 UI 全流程）", "tests/test_e2e_ui.py"),
]


def run_suite(name, path):
    junit = os.path.join(REPORTS, "junit_%s.xml" % os.path.basename(path).replace(".py", ""))
    cmd = [sys.executable, "-m", "pytest", path, "-q", "-p", "no:cacheprovider",
           "--junitxml=" + junit, "--tb=short"]
    start = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    dur = round(time.time() - start, 2)
    out = proc.stdout
    passed = failed = errors = skipped = 0
    line = ""
    for ln in out.splitlines():
        ln = ln.strip()
        if "passed" in ln or "failed" in ln or "error" in ln:
            line = ln
    import re
    m = re.search(r"(\d+) passed", line)
    passed = int(m.group(1)) if m else 0
    m = re.search(r"(\d+) failed", line)
    failed = int(m.group(1)) if m else 0
    m = re.search(r"(\d+) error", line)
    errors = int(m.group(1)) if m else 0
    m = re.search(r"(\d+) skipped", line)
    skipped = int(m.group(1)) if m else 0
    return {"name": name, "file": path, "passed": passed, "failed": failed,
            "errors": errors, "skipped": skipped, "duration": dur,
            "exit": proc.returncode, "tail": out.strip().splitlines()[-4:] if out.strip() else []}


def main():
    print("=" * 64)
    print("飞鹰CRM系统 · 质量门禁（三层自动化测试）")
    print("=" * 64)
    results = []
    for name, path in SUITES:
        print("\n▶ %s  (%s)" % (name, path))
        r = run_suite(name, path)
        results.append(r)
        mark = "PASS" if r["exit"] == 0 else "FAIL"
        print("  %s — 通过 %d / 失败 %d / 错误 %d，用时 %.1fs"
              % (mark, r["passed"], r["failed"], r["errors"], r["duration"]))
        for ln in r["tail"]:
            print("    | " + ln)

    total_p = sum(r["passed"] for r in results)
    total_f = sum(r["failed"] + r["errors"] for r in results)
    total_d = round(sum(r["duration"] for r in results), 1)
    ok = total_f == 0 and all(r["exit"] == 0 for r in results)

    shots = sorted(os.listdir(os.path.join(REPORTS, "screenshots")))
    summary = {
        "project": "飞鹰CRM系统 Feiying CRM",
        "version": "1.0.0",
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "suites": results,
        "total_passed": total_p, "total_failed": total_f, "duration_sec": total_d,
        "gate": "PASS" if ok else "FAIL",
        "screenshots": shots,
    }
    with io.open(os.path.join(REPORTS, "test_report.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    lines = [
        "# 飞鹰CRM系统 · 测试执行摘要",
        "",
        "- 执行时间：%s" % summary["date"],
        "- 版本：%s" % summary["version"],
        "- 结论：**%s**（共 %d 项，通过 %d，失败 %d，用时 %.1f 秒）" %
        (summary["gate"], total_p + total_f, total_p, total_f, total_d),
        "",
        "| 套件 | 通过 | 失败 | 用时(s) | 结果 |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        lines.append("| %s | %d | %d | %.1f | %s |" %
                     (r["name"], r["passed"], r["failed"] + r["errors"], r["duration"],
                      "PASS" if r["exit"] == 0 else "FAIL"))
    lines += ["", "截图产物 %d 张（reports/screenshots/）。" % len(shots), ""]
    with io.open(os.path.join(REPORTS, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("\n" + "=" * 64)
    print("总计：%d 项，通过 %d，失败 %d，用时 %.1fs → 门禁 %s"
          % (total_p + total_f, total_p, total_f, total_d, summary["gate"]))
    print("报告：reports/test_report.json · reports/summary.md · junit_*.xml")
    print("=" * 64)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
