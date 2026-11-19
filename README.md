# Bizyl — Backend & Applied NLP Engineering Challenge

## 1. How to Run

```bash
pip install -r requirements.txt

# Task 1: Hierarchical CV Domain Routing, Skill Mapping & S3 Flywheel Envelope
python cv_pipeline.py

# Task 2: Deterministic Job Board Hygiene & UI Filter Mapping
python job_hygiene.py

```

Generated deliverables:

- `outputs/parsed_cvs.json` (all 3 synthetic CVs)
- `outputs/cleaned_jobs.json` (all 6 job records)

---

## 2. How Domain Drift, Collisions & Schema Failures Were Prevented

### Task 1 (`cv_pipeline.py`)

- **Stage 1 — Hierarchical Domain Gate:** Scores domain and job-category signals against allowed enums (`Information Technology`, `Marketing`, `Consulting`, `Finance`) using Pydantic `Literal` types so multi-domain (`CV_002_COMPLEX_HYBRID`) and career-switcher (`CV_003_NOISY_SWITCHER`) CVs map to valid categories without inventing new ones.
- **Stage 2 — Scoped Extraction & Zero-Hallucination Quarantine:** Only taxonomy rows from Stage-1 locked domains are injected into extraction. Word-boundary lookarounds (`(?<![A-Za-z0-9_])term(?![A-Za-z0-9_])`) prevent substring collisions (such as `"Go"` inside `"Google Ads"` or `"R"` inside `"R&D"`). Legitimate skills absent from `sandbox_taxonomy.json` are routed to `other_skills_pending_approval` instead of being force-fit into unrelated taxonomy nodes.
- **Stage 3 — S3 Training-Flywheel Envelope:** Outputs `cv_id`, `raw_text`, `stage1_routing`, `model_extracted_profile`, a deep-copied `user_verified_profile`, and `diff_log: []` so downstream user edits on Bizyl can accumulate clean fine-tuning pairs.

### Task 2 (`job_hygiene.py`)

- **Soft-404 & HTML Cleanup:** Unescapes HTML entities (`&amp;`, `&mdash;`, `&ndash;`) via `html.unescape()` and flags closed/expired or 404 postings (`JB_102`, `JB_105`) with `is_active: false` and `inactive_reason`.
- **Contradiction Detection & Filter Mapping:** Flags mismatches between `raw_location` and `raw_page_snippet` (e.g., `JB_101` listing `"Remote Anywhere"` while snippet states `"Must reside in the United States or Canada"` -> classified as `"Remote (Restricted)"`) and maps active records strictly to Bizyl's allowed `employment_type`, `remote_scope`, `mapped_domain`, and `seniority` enums.

---

## 3. Task 3: End-to-End Bizyl Profile Snapshot Audit

After uploading `resume_mdakeel.pdf` on `bizyl.com` and inspecting the profile and Profile Snapshot (`[https://bizyl.com/profile-snapshot/f86ffcf2-b815-4bac-bea9-4a97550def75](https://bizyl.com/profile-snapshot/f86ffcf2-b815-4bac-bea9-4a97550def75)`), here are the 4 key issues observed and how I would fix them:

1. **Candidate Name & Location Extraction Mismatch (`Profile Details`):**

- _Observation:_ The profile populated `"Java"` and `"Prog - 1"` instead of `"Md Akeel"` from the resume header, and left City, State, and Postal Code blank while setting Country to `"IN"`.

- _Fix:_ Extract candidate name and contact fields directly from the top resume header/contact anchor block before falling back to account/OAuth display names, and parse/normalize location components into structured city, state, country, and postal fields.

2. **Project Misclassified into Work History & Split Project Cards (`Work History` & `Projects`):**

- _Observation:_ `TaskiFy` (listed under `PROJECTS` in the resume) appeared inside `Work History`, while `Projects` contained fragmented entries (`"Developed an Full Stack Website using MERN Stack"`, `"This project"`, `"MERN Stack This project"`).

- _Fix:_ Enforce section-header segmentation (`EXPERIENCE` vs. `PROJECTS`) in the parser and merge/deduplicate fragmented lines belonging to a single project entry before saving.

3. **Taxonomy Role Mapping & Empty `Other Skills` (`Skills` & `Other Skills`):**

- _Observation:_ `Figma` was mapped to `Design Systems Designer` and `Git` to `DevOps Engineer`, while `Other Skills` showed no secondary skills despite unmapped tools/frameworks present on the resume.

- _Fix:_ Restrict skill matching to domain-scoped taxonomy nodes with boundary checks and route non-taxonomy skills into `other_skills_pending_approval` via FastAPI/Pydantic instead of leaving them uncaptured.

4. **Workspace Loading Screen on Every Tab Switch:**

- _Observation:_ Switching across profile tabs (`Skills`, `Other Skills`, `Work History`, `Education`, `Achievements`, `Resume`, `Languages`, `Projects`) repeatedly displayed `"Opening Bizyl! Your workspace is loading."`
- _Fix:_ Cache the parsed profile sections in frontend state/Redis after initial load and serve partial section updates via FastAPI `PATCH` endpoints without full-tab reload screens.
