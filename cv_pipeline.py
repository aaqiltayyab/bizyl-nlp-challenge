import copy
import json
import os
import re
from pathlib import Path
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, model_validator

try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# --- STRICT ENUMS ---
AllowedDomain = Literal["Information Technology", "Marketing", "Consulting", "Finance"]
AllowedCategory = Literal[
    "Data and Artificial Intelligence",
    "Software Engineering",
    "Cloud and Infrastructure",
    "Growth and Performance Media",
    "Strategy and Corporate Advisory",
    "Corporate Finance and Strategic Planning",
]


class Stage1Routing(BaseModel):
    primary_domain: AllowedDomain
    primary_job_category: AllowedCategory
    secondary_domains: List[AllowedDomain] = Field(default_factory=list)
    secondary_job_categories: List[AllowedCategory] = Field(default_factory=list)


class MappedSkill(BaseModel):
    domain: AllowedDomain
    job_category: AllowedCategory
    job_title: str
    core_skill: str
    sub_skill: str
    matched_evidence: str


class ExtractedProfile(BaseModel):
    candidate_name: str
    mapped_skills: List[MappedSkill]
    other_skills_pending_approval: List[str] = Field(default_factory=list)


class S3FlywheelEnvelope(BaseModel):
    cv_id: str
    raw_text: str
    stage1_routing: Stage1Routing
    model_extracted_profile: ExtractedProfile
    user_verified_profile: ExtractedProfile
    diff_log: List[dict] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_initial_verified_copy(self):
        if not self.diff_log and self.user_verified_profile != self.model_extracted_profile:
            self.user_verified_profile = copy.deepcopy(self.model_extracted_profile)
        return self


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def exact_term_match(term: str, text: str) -> bool:
    """Matches standalone tokens/phrases while avoiding substring collisions like 'Go' in 'Google Ads'."""
    pattern = rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])"
    return bool(re.search(pattern, text, flags=re.IGNORECASE))


def stage1_domain_gate(raw_text: str, taxonomy: List[dict]) -> Stage1Routing:
    normalized_text = raw_text.replace("/", " ")
    domain_hits: dict[str, int] = {}
    category_hits: dict[str, int] = {}

    for row in taxonomy:
        syn = row["Synonym"]
        sub = row["Sub Skill"]
        if exact_term_match(syn, normalized_text) or exact_term_match(sub, normalized_text):
            d = row["Domain"]
            c = row["Job Category"]
            domain_hits[d] = domain_hits.get(d, 0) + 1
            category_hits[c] = category_hits.get(c, 0) + 1

    if not domain_hits:
        return Stage1Routing(
            primary_domain="Information Technology",
            primary_job_category="Software Engineering",
        )

    ranked_domains = sorted(domain_hits.items(), key=lambda x: x[1], reverse=True)
    ranked_categories = sorted(category_hits.items(), key=lambda x: x[1], reverse=True)

    return Stage1Routing(
        primary_domain=ranked_domains[0][0],
        primary_job_category=ranked_categories[0][0],
        secondary_domains=[d for d, _ in ranked_domains[1:]],
        secondary_job_categories=[c for c, _ in ranked_categories[1:]],
    )


def extract_other_skills(raw_text: str, mapped_evidences: set[str], candidate_name: str) -> List[str]:
    """Extracts legitimate skills not present in the sandbox taxonomy without hallucinating."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if HAS_GENAI and api_key:
        try:
            client = genai.Client(api_key=api_key)
            prompt = (
                "Extract ONLY legitimate technical, analytical, or business skills/tools from the CV below "
                f"that are NOT already in this matched list: {sorted(mapped_evidences)}. "
                "Exclude names, locations, companies, degrees, dates, and generic soft words. "
                'Return strict JSON: {"other_skills": ["..."]}.\n\n'
                f"CV:\n{raw_text}"
            )
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            parsed = json.loads(response.text)
            items = parsed.get("other_skills", [])
            if isinstance(items, list):
                return [str(x).strip() for x in items if str(x).strip()]
        except Exception as exc:
            print(f"[Note] Falling back to deterministic skill extractor for {candidate_name}: {exc}")

    candidate_catalog = [
        "PostgreSQL",
        "FastAPI",
        "Pydantic",
        "Redis",
        "Docker",
        "Regex",
        "Go-To-Market Strategy",
        "SQL",
        "Looker Studio",
        "A/B Landing Page Tests",
        "Due Diligence",
        "pandas",
        "SHAP",
        "LangGraph",
    ]
    mapped_lower = {item.lower() for item in mapped_evidences}
    quarantined = []
    for skill in candidate_catalog:
        if exact_term_match(skill, raw_text) and skill.lower() not in mapped_lower:
            quarantined.append(skill)
    return quarantined


def process_cv(cv_item: dict, taxonomy: List[dict]) -> S3FlywheelEnvelope:
    cv_id = cv_item["cv_id"]
    raw_text = cv_item["raw_text"]

    first_line = raw_text.splitlines()[0]
    candidate_name = re.split(r"[|\-]", first_line)[0].strip().title()

    routing = stage1_domain_gate(raw_text, taxonomy)
    active_domains = {routing.primary_domain, *routing.secondary_domains}

    scoped_rows = [row for row in taxonomy if row["Domain"] in active_domains]
    normalized_text = raw_text.replace("/", " ")

    mapped_skills: List[MappedSkill] = []
    matched_evidences: set[str] = set()

    for row in scoped_rows:
        syn = row["Synonym"]
        sub = row["Sub Skill"]
        evidence: Optional[str] = None

        if exact_term_match(syn, normalized_text):
            evidence = syn
        elif exact_term_match(sub, normalized_text):
            evidence = sub

        if evidence:
            matched_evidences.add(evidence)
            mapped_skills.append(
                MappedSkill(
                    domain=row["Domain"],
                    job_category=row["Job Category"],
                    job_title=row["Job Title"],
                    core_skill=row["Core Skill"],
                    sub_skill=row["Sub Skill"],
                    matched_evidence=evidence,
                )
            )

    other_skills = extract_other_skills(raw_text, matched_evidences, candidate_name)

    extracted = ExtractedProfile(
        candidate_name=candidate_name,
        mapped_skills=mapped_skills,
        other_skills_pending_approval=other_skills,
    )

    return S3FlywheelEnvelope(
        cv_id=cv_id,
        raw_text=raw_text,
        stage1_routing=routing,
        model_extracted_profile=extracted,
        user_verified_profile=copy.deepcopy(extracted),
        diff_log=[],
    )


def main():
    taxonomy = load_json("sandbox_taxonomy.json")
    cvs = load_json("synthetic_cvs.json")

    envelopes = [process_cv(cv, taxonomy).model_dump() for cv in cvs]

    Path("outputs").mkdir(exist_ok=True)
    output_file = Path("outputs/parsed_cvs.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(envelopes, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(envelopes)} CV envelopes to {output_file}")


if __name__ == "__main__":
    main()