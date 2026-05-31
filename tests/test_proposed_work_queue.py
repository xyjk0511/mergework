from __future__ import annotations

import json
import subprocess
import sys

from scripts import proposed_work_queue
from scripts.proposed_work_queue import (
    analyze_queue,
    format_markdown_report,
    format_text_report,
    main,
)


def _body(*sections: str) -> str:
    return "\n\n".join(f"## {section}\n\nFixture text." for section in sections)


def _fixture() -> dict[str, object]:
    return {
        "issues": [
            {
                "number": 671,
                "title": "Proposed work: add queue report",
                "url": "https://github.com/ramimbo/mergework/issues/671",
                "state": "OPEN",
                "labels": [{"name": "proposed-work"}],
                "body": "A maintainer-labeled issue keeps working.",
            },
            {
                "number": 684,
                "title": "Proposed work: handle unlabeled proposed-work intake",
                "url": "https://github.com/ramimbo/mergework/issues/684",
                "state": "OPEN",
                "labels": [],
                "body": _body(
                    "Problem",
                    "Evidence",
                    "Proposed work",
                    "Expected value",
                    "Possible acceptance criteria",
                    "Evidence or tests required",
                    "Duplicate search",
                    "Out of scope",
                ),
            },
            {
                "number": 685,
                "title": "Proposed work: vague title only",
                "url": "https://github.com/ramimbo/mergework/issues/685",
                "state": "OPEN",
                "labels": [],
                "body": "This is missing the template sections.",
            },
            {
                "number": 686,
                "title": "MRWK bounty: unrelated live bounty",
                "url": "https://github.com/ramimbo/mergework/issues/686",
                "state": "OPEN",
                "labels": [{"name": "mrwk:bounty"}],
                "body": _body("Problem", "Proposed work"),
            },
        ]
    }


def test_analyze_queue_keeps_labeled_and_unlabeled_template_intake() -> None:
    report = analyze_queue(_fixture())

    assert report["summary"] == {
        "issues": 4,
        "proposed_work_issues": 2,
        "open_proposed_work_issues": 2,
        "labeled_proposed_work": 1,
        "unlabeled_fallback_proposed_work": 1,
        "invalid_title_only": 1,
    }
    assert [item["number"] for item in report["proposed_work"]] == [671, 684]
    assert report["proposed_work"][0]["classification"] == "labeled"
    assert report["proposed_work"][1]["classification"] == "unlabeled_fallback"
    assert [item["number"] for item in report["unlabeled_fallback"]] == [684]
    assert [item["number"] for item in report["invalid_title_only"]] == [685]


def test_unlabeled_fallback_requires_title_and_complete_template_body() -> None:
    report = analyze_queue(
        {
            "issues": [
                {
                    "number": 1,
                    "title": "Proposed work: title only",
                    "labels": [],
                    "state": "OPEN",
                    "body": _body("Problem"),
                },
                {
                    "number": 2,
                    "title": "Idea: body only",
                    "labels": [],
                    "state": "OPEN",
                    "body": _body("Problem", "Proposed work"),
                },
            ]
        }
    )

    assert report["summary"]["proposed_work_issues"] == 0
    assert report["summary"]["invalid_title_only"] == 1
    assert report["invalid_title_only"][0]["detail"] == (
        "Title matches Proposed work:, but body is missing: Evidence, Proposed work, "
        "Expected value, Possible acceptance criteria, Evidence or tests required, "
        "Duplicate search, Out of scope"
    )


def test_unlabeled_fallback_rejects_partial_template_body() -> None:
    report = analyze_queue(
        {
            "issues": [
                {
                    "number": 3,
                    "title": "Proposed work: missing duplicate search",
                    "labels": [],
                    "state": "OPEN",
                    "body": _body(
                        "Problem",
                        "Evidence",
                        "Proposed work",
                        "Expected value",
                        "Possible acceptance criteria",
                        "Evidence or tests required",
                        "Out of scope",
                    ),
                },
            ]
        }
    )

    assert report["summary"]["proposed_work_issues"] == 0
    assert report["summary"]["invalid_title_only"] == 1
    assert report["invalid_title_only"][0]["detail"] == (
        "Title matches Proposed work:, but body is missing: Duplicate search"
    )


def test_format_reports_call_out_unlabeled_fallback() -> None:
    report = analyze_queue(_fixture())
    text = format_text_report(report)
    markdown = format_markdown_report(report)

    assert "unlabeled fallback proposed work: 1" in text
    assert "Issue #684: Proposed work: handle unlabeled proposed-work intake" in text
    assert "## Proposed-Work Intake Summary" in markdown
    assert "### Unlabeled proposed-work fallback" in markdown
    assert "[Issue #684](https://github.com/ramimbo/mergework/issues/684)" in markdown
    assert "valid intake candidates" in markdown


def test_main_reads_fixture_and_can_fail_on_unlabeled(tmp_path, capsys) -> None:
    input_path = tmp_path / "proposed-work.json"
    input_path.write_text(json.dumps(_fixture()), encoding="utf-8")

    exit_code = main(["--input", str(input_path), "--format", "json"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["summary"]["unlabeled_fallback_proposed_work"] == 1
    assert main(["--input", str(input_path), "--fail-on-unlabeled"]) == 1


def test_main_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/proposed_work_queue.py", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "proposed-work issue intake" in result.stdout


def test_load_live_queue_uses_read_only_issue_list(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(*args, **kwargs):  # noqa: ANN002, ANN003
        calls.append(args[0])
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "number": 684,
                        "title": "Proposed work: fallback",
                        "labels": [],
                        "state": "OPEN",
                        "body": _body(
                            "Problem",
                            "Evidence",
                            "Proposed work",
                            "Expected value",
                            "Possible acceptance criteria",
                            "Evidence or tests required",
                            "Duplicate search",
                            "Out of scope",
                        ),
                    }
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr(proposed_work_queue.subprocess, "run", fake_run)

    assert proposed_work_queue.load_live_queue("ramimbo/mergework")["issues"][0]["number"] == 684
    assert calls == [
        [
            "gh",
            "issue",
            "list",
            "--repo",
            "ramimbo/mergework",
            "--state",
            "all",
            "--limit",
            str(proposed_work_queue.GH_ISSUE_SAFETY_CAP),
            "--json",
            "number,title,url,body,labels,state",
        ]
    ]
