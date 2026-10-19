"""ATS verification for the resume PDF and per-job keyword coverage.

Two checks, adapted from the drafter-reviewer PDF/ATS idea (MadsLorentzen/ai-job-search),
reimplemented for this tool where the resume is a fixed PDF (no generated LaTeX CV):

1. parseability(): read the resume PDF's TEXT LAYER the way an ATS parser does and flag
   problems — missing/garbled contact details, non-extractable text, suspiciously low text
   (likely an image-only/scanned PDF an ATS cannot read).
2. keyword_coverage(): score how many of a job posting's salient terms actually appear in the
   resume text. Honesty rule: report gaps, never suggest stuffing. Pure signal, no mutation.
"""
import re
import logging

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(\+?\d[\d\-\s().]{7,}\d)")
URL_RE = re.compile(r"(linkedin\.com/|github\.com/|https?://)", re.I)

# Generic words to ignore when extracting a posting's "salient" keywords.
_STOP = set("""a an the and or of to in for with on at by from as is are be will you we our your their
this that these those it its role team work experience years using used help build built strong
ability excellent good great plus etc including include across within per into out over more most
who what when where how why which can may should must have has had do does job position candidate
requirements responsibilities qualifications preferred required nice looking seeking able""".split())


def parseability(resume_text: str, pdf_path: str = "") -> dict:
    """Return {ok, score, issues[], found{email,phone,links}}. Judges ATS-readability."""
    issues = []
    txt = resume_text or ""
    words = txt.split()
    # 1) extractable text at all?
    if len(words) < 150:
        issues.append(f"Low extractable text ({len(words)} words) — the PDF may be image-only "
                      "or scanned, which many ATS parsers cannot read.")
    # 2) contact details present as real text
    email = EMAIL_RE.search(txt)
    phone = PHONE_RE.search(txt)
    links = URL_RE.search(txt)
    if not email:
        issues.append("No email found in the text layer — an ATS may not capture your contact email.")
    if not phone:
        issues.append("No phone number found in the text layer.")
    if not links:
        issues.append("No LinkedIn/GitHub/portfolio URL found as selectable text.")
    # 3) garbled-glyph heuristic: lots of replacement chars or isolated single chars = bad font encoding
    bad = txt.count("\ufffd") + txt.count("\x00")
    if bad > 3:
        issues.append(f"{bad} unreadable/replacement characters — a font-encoding problem that "
                      "makes the PDF extract as garbage for an ATS.")
    # 4) reading-order smell: very long runs with no spaces (multi-column bleed)
    if re.search(r"\S{45,}", txt):
        issues.append("Found very long unbroken character runs — possible multi-column layout that "
                      "an ATS may read out of order.")
    score = max(0, 100 - 22 * len(issues))
    return {
        "ok": not issues,
        "score": score,
        "issues": issues,
        "found": {"email": bool(email), "phone": bool(phone), "links": bool(links),
                  "words": len(words)},
    }


def _keywords(job_text: str, limit: int = 25) -> list[str]:
    """Pull salient, de-duplicated keyword candidates from a job posting."""
    text = re.sub(r"<[^>]+>", " ", job_text or "")
    # keep multiword tech-ish tokens and capitalized/dotted terms, plus plain words
    cand = re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{2,}", text)
    cand = [w.strip(".-") for w in cand]
    seen, out = set(), []
    for w in cand:
        lw = w.lower()
        if lw in _STOP or len(lw) < 3 or lw.isdigit():
            continue
        if lw not in seen:
            seen.add(lw)
            out.append(w)
    # prioritize terms that look like skills/tech (contain digit, +, #, ., or are capitalized)
    out.sort(key=lambda w: (0 if re.search(r"[0-9+#.]", w) or w[0].isupper() else 1))
    return out[:limit]


def keyword_coverage(resume_text: str, job_text: str) -> dict:
    """Return {coverage_pct, matched[], missing[]} — how the resume reads against the posting.

    Honesty rule: missing[] is reported as genuine gaps. Never auto-insert these into a resume.
    """
    rtext = (resume_text or "").lower()
    kws = _keywords(job_text)
    matched, missing = [], []
    for k in kws:
        # word-ish containment (handles 'AWS', 'Kubernetes', 'CI/CD', 'Python3')
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(k.lower()) + r"(?![A-Za-z0-9])", rtext):
            matched.append(k)
        else:
            missing.append(k)
    total = len(matched) + len(missing)
    pct = round(100 * len(matched) / total) if total else 0
    return {"coverage_pct": pct, "matched": matched, "missing": missing}


def report(resume_text: str, job_text: str, pdf_path: str = "") -> str:
    """One compact human-readable block for Slack/CLI."""
    p = parseability(resume_text, pdf_path)
    cov = keyword_coverage(resume_text, job_text)
    lines = [f"🧪 *ATS check* — resume parseability {p['score']}/100"
             + ("" if p["ok"] else f" ({len(p['issues'])} issue(s))"),
             f"🔑 Keyword coverage vs this posting: *{cov['coverage_pct']}%*"]
    if cov["missing"]:
        lines.append("Gaps (present in posting, not in resume — do NOT keyword-stuff; add only if true): "
                     + ", ".join(cov["missing"][:10]))
    for iss in p["issues"]:
        lines.append("• " + iss)
    return "\n".join(lines)
