from __future__ import annotations

from pathlib import Path

from extraction.paths import REPORTS_DIR, ensure_output_dirs
from extraction.schemas import ExtractionResult


def write_markdown_report(result: ExtractionResult, output_dir: Path = REPORTS_DIR) -> str:
    ensure_output_dirs()
    lines = [
        f"# {result.code} 추출 검수 리포트",
        "",
        f"- validationPassed: `{result.validationPassed}`",
        f"- model: `{result.model}`",
        f"- promptVersion: `{result.promptVersion}`",
        f"- promptInput: `{result.promptInput}`",
    ]
    if result.source:
        lines.append(f"- source: `{result.source.filename}`")
        if result.source.sha256:
            lines.append(f"- sha256: `{result.source.sha256}`")
    lines.extend(["", "## 필드", ""])
    profile = result.profile
    for field in (
        "name",
        "code",
        "market",
        "baseIndex",
        "replication",
        "leverage",
        "strategy",
        "distribution",
        "totalExpense",
        "fxHedge",
    ):
        lines.append(f"- `{field}`: {getattr(profile, field)}")
    lines.extend(["", "## Evidence", ""])
    for evidence in profile.evidence:
        lines.append(f"- `{evidence.field}` {evidence.location}: {evidence.quote}")
    lines.extend(["", "## 검증 이슈", ""])
    if result.issues:
        for issue in result.issues:
            lines.append(f"- `{issue.code}` `{issue.field}`: {issue.message}")
    else:
        lines.append("- 없음")

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result.code}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)
