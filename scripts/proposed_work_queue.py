from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any

PROPOSED_WORK_LABEL = "proposed-work"
PROPOSED_WORK_TITLE_RE = re.compile(r"^\s*proposed\s+work\s*:", re.IGNORECASE)
SECTION_RE_TEMPLATE = r"(?im)^\s*(?:#{{1,6}}\s*)?{section}\s*$"
REQUIRED_FALLBACK_SECTIONS = (
    "Problem",
    "Evidence",
    "Proposed work",
    "Expected value",
    "Possible acceptance criteria",
    "Evidence or tests required",
    "Duplicate search",
    "Out of scope",
)
GH_TIMEOUT_SECONDS = 30
GH_ISSUE_SAFETY_CAP = 201


def _labels(raw: dict[str, Any]) -> list[str]:
    labels = raw.get("labels", [])
    names: list[str] = []
    for label in labels:
        if isinstance(label, str):
            names.append(label)
        elif isinstance(label, dict) and isinstance(label.get("name"), str):
            names.append(label["name"])
    return names


def _has_label(raw: dict[str, Any], label_name: str) -> bool:
    return any(label.lower() == label_name for label in _labels(raw))


def _has_title_marker(raw: dict[str, Any]) -> bool:
    return bool(PROPOSED_WORK_TITLE_RE.match(str(raw.get("title") or "")))


def _has_section(body: str, section: str) -> bool:
    pattern = SECTION_RE_TEMPLATE.format(section=re.escape(section))
    return bool(re.search(pattern, body))


def _missing_fallback_sections(raw: dict[str, Any]) -> list[str]:
    body = str(raw.get("body") or "")
    return [section for section in REQUIRED_FALLBACK_SECTIONS if not _has_section(body, section)]


def _single_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def _issue_summary(raw: dict[str, Any], classification: str, detail: str) -> dict[str, Any]:
    return {
        "number": int(raw["number"]),
        "title": str(raw.get("title") or ""),
        "url": raw.get("url"),
        "state": str(raw.get("state") or "").lower(),
        "labels": sorted(label.lower() for label in _labels(raw)),
        "classification": classification,
        "detail": detail,
    }


def analyze_queue(data: dict[str, Any]) -> dict[str, Any]:
    issues = [item for item in data.get("issues", []) if isinstance(item, dict)]
    normalized_issues = [issue for issue in issues if isinstance(issue.get("number"), int)]

    labeled: list[dict[str, Any]] = []
    fallback: list[dict[str, Any]] = []
    invalid_title_only: list[dict[str, Any]] = []

    for issue in normalized_issues:
        has_label = _has_label(issue, PROPOSED_WORK_LABEL)
        has_title = _has_title_marker(issue)
        missing_sections = _missing_fallback_sections(issue)

        if has_label:
            detail = "Has proposed-work label"
            labeled.append(_issue_summary(issue, "labeled", detail))
        elif has_title and not missing_sections:
            detail = (
                "Missing proposed-work label, but title and template body match "
                "proposed-work intake"
            )
            fallback.append(_issue_summary(issue, "unlabeled_fallback", detail))
        elif has_title:
            missing = ", ".join(missing_sections)
            detail = f"Title matches Proposed work:, but body is missing: {missing}"
            invalid_title_only.append(_issue_summary(issue, "invalid_title_only", detail))

    proposed_work = sorted(
        [*labeled, *fallback],
        key=lambda item: item["number"],
    )
    open_count = sum(1 for item in proposed_work if item["state"] == "open")
    report = {
        "summary": {
            "issues": len(normalized_issues),
            "proposed_work_issues": len(proposed_work),
            "open_proposed_work_issues": open_count,
            "labeled_proposed_work": len(labeled),
            "unlabeled_fallback_proposed_work": len(fallback),
            "invalid_title_only": len(invalid_title_only),
        },
        "proposed_work": proposed_work,
        "unlabeled_fallback": sorted(fallback, key=lambda item: item["number"]),
        "invalid_title_only": sorted(invalid_title_only, key=lambda item: item["number"]),
    }
    return report


def has_unlabeled_fallback(report: dict[str, Any]) -> bool:
    return bool(report["unlabeled_fallback"])


def format_text_report(report: dict[str, Any]) -> str:
    lines = ["Proposed-work intake summary"]
    for key, value in report["summary"].items():
        lines.append(f"- {key.replace('_', ' ')}: {value}")
    if not report["proposed_work"]:
        lines.append("")
        lines.append("No proposed-work intake issues found.")
        return "\n".join(lines)

    if report["unlabeled_fallback"]:
        lines.append("")
        lines.append("Unlabeled proposed-work fallback")
        for item in report["unlabeled_fallback"]:
            lines.append(f"- Issue #{item['number']}: {_single_line(item['title'])}")

    if report["invalid_title_only"]:
        lines.append("")
        lines.append("Invalid Proposed work: title-only matches")
        for item in report["invalid_title_only"]:
            lines.append(
                f"- Issue #{item['number']}: {_single_line(item['title'])} "
                f"({_single_line(item['detail'])})"
            )
    return "\n".join(lines)


def _markdown_issue(item: dict[str, Any]) -> str:
    issue_label = f"Issue #{item['number']}"
    url = item.get("url")
    if isinstance(url, str) and url:
        issue_label = f"[{issue_label}]({url})"
    return f"- {issue_label}: {_single_line(item['title'])} ({_single_line(item['detail'])})"


def format_markdown_report(report: dict[str, Any]) -> str:
    lines = ["## Proposed-Work Intake Summary", ""]
    for key, value in report["summary"].items():
        lines.append(f"- **{key.replace('_', ' ')}**: {value}")
    if not report["proposed_work"]:
        lines.append("")
        lines.append("No proposed-work intake issues found.")
        return "\n".join(lines)

    if report["unlabeled_fallback"]:
        lines.append("")
        lines.append("### Unlabeled proposed-work fallback")
        lines.append("")
        lines.append(
            "These issues are valid intake candidates even though the contributor could "
            "not attach the `proposed-work` label."
        )
        for item in report["unlabeled_fallback"]:
            lines.append(_markdown_issue(item))

    if report["invalid_title_only"]:
        lines.append("")
        lines.append("### Invalid `Proposed work:` title-only matches")
        for item in report["invalid_title_only"]:
            lines.append(_markdown_issue(item))
    return "\n".join(lines)


def _run_gh_json(args: list[str]) -> Any:
    command = " ".join(args)
    try:
        completed = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"gh command timed out after {GH_TIMEOUT_SECONDS}s: {command}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "gh command failed "
            f"(exit {exc.returncode}): {command}\n"
            f"stdout:\n{exc.stdout or exc.output or ''}\n"
            f"stderr:\n{exc.stderr or ''}"
        ) from exc
    return json.loads(completed.stdout)


def load_live_queue(repo: str) -> dict[str, Any]:
    issues = _run_gh_json(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "all",
            "--limit",
            str(GH_ISSUE_SAFETY_CAP),
            "--json",
            "number,title,url,body,labels,state",
        ]
    )
    if len(issues) >= GH_ISSUE_SAFETY_CAP:
        raise RuntimeError(
            f"gh issue list reached the {GH_ISSUE_SAFETY_CAP} item safety cap; "
            "use an API-paginated collector before trusting this live report"
        )
    return {"issues": issues}


def _load_input(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("proposed-work queue input must be a JSON object")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize MergeWork proposed-work issue intake, including unlabeled fallbacks."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="Read proposed-work issue data from a JSON fixture file.")
    source.add_argument(
        "--repo",
        help="Collect live proposed-work issue data with gh, for example ramimbo/mergework.",
    )
    parser.add_argument("--format", choices=["json", "markdown", "text"], default="text")
    parser.add_argument("--fail-on-unlabeled", action="store_true")
    args = parser.parse_args(argv)

    data = _load_input(args.input) if args.input else load_live_queue(args.repo)
    report = analyze_queue(data)
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif args.format == "markdown":
        print(format_markdown_report(report))
    else:
        print(format_text_report(report))
    return 1 if args.fail_on_unlabeled and has_unlabeled_fallback(report) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
