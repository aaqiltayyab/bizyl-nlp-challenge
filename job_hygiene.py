import html
import json
import re
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel

EmploymentType = Literal["Full-time", "Part-time", "Contract", "Internship"]
RemoteScope = Literal["Remote (Global)", "Remote (Restricted)", "Hybrid", "On-site"]
MappedDomain = Literal["Information Technology", "Marketing", "Consulting", "Finance"]
SeniorityLevel = Literal["Intern/Entry", "Mid-Level", "Senior", "Lead/Executive"]


class CleanedJobRecord(BaseModel):
    job_id: str
    clean_title: str
    clean_location: str
    clean_snippet: str
    is_active: bool
    inactive_reason: Optional[str] = None
    contradiction_detected: bool = False
    contradiction_note: Optional[str] = None
    employment_type: Optional[EmploymentType] = None
    remote_scope: Optional[RemoteScope] = None
    mapped_domain: Optional[MappedDomain] = None
    seniority: Optional[SeniorityLevel] = None


SOFT_404_RULES: list[tuple[str, str]] = [
    (r"no longer available", "Listing is marked as no longer available"),
    (r"has been filled", "Position has already been filled"),
    (r"position has been closed", "Position has been closed"),
    (r"404 not found", "Soft 404 / Requisition ID does not exist"),
    (r"does not exist", "Requested requisition does not exist"),
]


def check_soft_404(snippet: str) -> tuple[bool, Optional[str]]:
    lower_snippet = snippet.lower()
    for pattern, reason in SOFT_404_RULES:
        if re.search(pattern, lower_snippet):
            return False, reason
    return True, None


def detect_remote_scope_and_contradiction(
    clean_location: str, clean_snippet: str
) -> tuple[RemoteScope, bool, Optional[str]]:
    loc_l = clean_location.lower()
    snip_l = clean_snippet.lower()

    if "hybrid" in loc_l or "hybrid" in snip_l:
        return "Hybrid", False, None
    if "on-site" in loc_l or "onsite" in loc_l or "on-site" in snip_l:
        return "On-site", False, None

    claims_global = any(token in loc_l for token in ["anywhere", "global", "worldwide"])
    restriction_match = re.search(
        r"(must reside in [^.!]+|only|united states|canada|uk|eu|india)",
        snip_l,
    )
    loc_has_restriction = bool(re.search(r"(only|india|uk|eu|us|canada)", loc_l))

    if claims_global and restriction_match:
        note = (
            f"Location '{clean_location}' conflicts with snippet restriction: "
            f"'{restriction_match.group(0).strip()}'"
        )
        return "Remote (Restricted)", True, note

    if loc_has_restriction or restriction_match:
        return "Remote (Restricted)", False, None

    return "Remote (Global)", False, None


def map_employment_type(hint: str, snippet: str) -> EmploymentType:
    text = f"{hint} {snippet}".lower()
    if "intern" in text:
        return "Internship"
    if "contract" in text:
        return "Contract"
    if "part time" in text or "part-time" in text or "20 hrs/week" in text:
        return "Part-time"
    return "Full-time"


def map_domain(title: str, snippet: str) -> MappedDomain:
    text = f"{title} {snippet}".lower()
    if any(k in text for k in ["python", "django", "pyspark", "ai", "ml", "nlp", "data engineer"]):
        return "Information Technology"
    if any(k in text for k in ["growth", "paid search", "meta ads", "conversions api"]):
        return "Marketing"
    if any(k in text for k in ["strategy", "tam/sam/som", "porter five forces", "consultant"]):
        return "Consulting"
    return "Finance"


def map_seniority(title: str, snippet: str) -> SeniorityLevel:
    text = f"{title} {snippet}".lower()
    if "intern" in text:
        return "Intern/Entry"
    if any(k in text for k in ["head", "director", "vp", "executive", "lead"]):
        return "Lead/Executive"
    if "senior" in text or "sr." in text:
        return "Senior"
    return "Mid-Level"


def clean_job_record(raw_job: dict) -> CleanedJobRecord:
    clean_title = html.unescape(raw_job["title"]).strip()
    clean_location = html.unescape(raw_job["raw_location"]).strip()
    clean_snippet = html.unescape(raw_job["raw_page_snippet"]).strip()

    is_active, inactive_reason = check_soft_404(clean_snippet)
    remote_scope, contradiction_flag, contradiction_note = (
        detect_remote_scope_and_contradiction(clean_location, clean_snippet)
    )

    if not is_active:
        return CleanedJobRecord(
            job_id=raw_job["job_id"],
            clean_title=clean_title,
            clean_location=clean_location,
            clean_snippet=clean_snippet,
            is_active=False,
            inactive_reason=inactive_reason,
            contradiction_detected=contradiction_flag,
            contradiction_note=contradiction_note,
            employment_type=None,
            remote_scope=None,
            mapped_domain=None,
            seniority=None,
        )

    return CleanedJobRecord(
        job_id=raw_job["job_id"],
        clean_title=clean_title,
        clean_location=clean_location,
        clean_snippet=clean_snippet,
        is_active=True,
        inactive_reason=None,
        contradiction_detected=contradiction_flag,
        contradiction_note=contradiction_note,
        employment_type=map_employment_type(raw_job.get("employment_hint", ""), clean_snippet),
        remote_scope=remote_scope,
        mapped_domain=map_domain(clean_title, clean_snippet),
        seniority=map_seniority(clean_title, clean_snippet),
    )


def main():
    with open("dirty_jobs.json", "r", encoding="utf-8") as f:
        raw_jobs = json.load(f)

    cleaned_jobs = [clean_job_record(job).model_dump() for job in raw_jobs]

    Path("outputs").mkdir(exist_ok=True)
    out_path = Path("outputs/cleaned_jobs.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cleaned_jobs, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(cleaned_jobs)} cleaned job records to {out_path}")


if __name__ == "__main__":
    main()