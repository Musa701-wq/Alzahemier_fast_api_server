from typing import Any, Dict


def _escape_pdf_text(text: str) -> str:
    ascii_safe = text.encode("ascii", errors="replace").decode("ascii")
    return ascii_safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def generate_report_pdf_bytes(summary_json: Dict[str, Any]) -> bytes:
    """
    Generates a valid one-page PDF document containing patient demographics,
    total & domain scores, per-test breakdown, user notes, and the mandatory
    screening-aid disclaimer footer.
    """
    patient = summary_json.get("patient", {})
    lines = [
        "YAADASHT - ONE-PAGE CLINICAL SCREENING REPORT",
        f"Patient: {patient.get('name', 'N/A')} | Age: {patient.get('age', 'N/A')} | Gender: {patient.get('gender', 'N/A')} | City: {patient.get('city', 'N/A')}",
        f"Date: {summary_json.get('session_date') or summary_json.get('period_end', 'N/A')}",
        f"Total Score: {summary_json.get('total_score', 'N/A')} | Outcome: {summary_json.get('outcome', 'N/A')}",
        f"Domain Scores: {summary_json.get('domain_scores', {})}",
    ]

    for item in summary_json.get("per_test_breakdown", []):
        lines.append(
            f"Test {item.get('test_number')} ({item.get('test_type')}): Score {item.get('score')}"
        )

    if "adherence_pct" in summary_json:
        lines.append(
            f"Monthly Medicine Adherence: {summary_json.get('adherence_pct')}% "
            f"(Taken: {summary_json.get('taken_count', 0)}, Skipped: {summary_json.get('skipped_count', 0)}, Missed: {summary_json.get('missed_count', 0)})"
        )

    if summary_json.get("user_notes"):
        lines.append(f"Notes for Doctor: {summary_json.get('user_notes')}")

    lines.append("Footer: Generated from a home screening, not a diagnosis.")
    lines.append(summary_json.get("disclaimer", "Screening aid only, please consult a doctor."))

    content_ops = ["BT", "/F1 11 Tf", "50 760 Td", "16 TL"]
    for idx, line in enumerate(lines):
        escaped = _escape_pdf_text(str(line))
        if idx == 0:
            content_ops.append(f"({escaped}) Tj")
        else:
            content_ops.append(f"T* ({escaped}) Tj")
    content_ops.append("ET")
    stream_data = "\n".join(content_ops).encode("ascii")

    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        f"5 0 obj\n<< /Length {len(stream_data)} >>\nstream\n".encode("ascii")
        + stream_data
        + b"\nendstream\nendobj\n",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)

    xref_pos = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        pdf.extend(f"{off:010d} 00000 n \n".encode("ascii"))

    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(pdf)

