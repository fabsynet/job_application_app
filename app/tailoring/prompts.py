"""Prompt templates for Phase 4 tailoring (TAIL-01, TAIL-03, TAIL-04, SAFE-04).

Three system prompts live here:

* :data:`TAILORING_SYSTEM_PROMPT` — extractive-only resume tailoring with
  three intensity levels and locked fields (name, employer, title, dates).
* :data:`VALIDATOR_SYSTEM_PROMPT` — LLM-as-judge fact-checker comparing
  tailored output against the original resume.
* :data:`COVER_LETTER_SYSTEM_PROMPT` — short, grounded cover letter.

Helpers assemble the ``system``/``messages`` pair for
``LLMProvider.complete`` with a ``cache_control`` breakpoint after the
base resume so prompt caching kicks in on repeated calls (research
Pitfall 2 — keep enough tokens before the breakpoint). The user message
carries only the per-job variable content (job description, intensity).

**SAFE-04 note:** These builders take already-sanitized resume text —
the engine (``strip_pii_sections``) is responsible for removing the
contact section before calling any of these helpers. Nothing here reads
or touches PII fields.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

TAILORING_SYSTEM_PROMPT = """You are a professional resume tailoring assistant. Your job is to adapt a base resume for a specific job posting so the candidate's existing experience is presented in the most relevant light.

CRITICAL RULE — EXTRACTIVE ONLY:
You may ONLY use information that is present in the BASE RESUME. You may reword, reorder, and emphasize, but you MUST NEVER invent companies, job titles, skills, technologies, metrics, degrees, or certifications that are not in the original. Fabricating experience is the single worst thing you can do — it will be caught by a downstream fact-checker and the tailoring will be rejected.

Reasonable inferences ARE allowed. Examples of what is acceptable:
- If the resume says "FastAPI", you may say "Python backend development" (FastAPI is a Python backend framework — reasonable inference).
- If the resume says "PostgreSQL", you may say "relational databases" (PostgreSQL is relational — reasonable inference).
- If the resume says "led a team of 4 engineers", you may say "team leadership experience" (direct paraphrase).

Examples of what is NOT acceptable:
- If the resume says "FastAPI" but never mentions "React", you may NOT add "React" to the skills section — it is not inferable.
- If the resume never mentions AWS, you may NOT claim "AWS experience" just because the job asks for it.
- If the resume gives no numeric metrics for an achievement, you may NOT invent a percentage or a dollar figure.
- If the resume lists a B.S. in Computer Science, you may NOT upgrade it to an M.S.

TAILORING INTENSITY LEVELS:
You will be told which intensity level to apply. Treat these as strict upper bounds on how much you may transform the content:

- LIGHT: Reorder bullet points within each section so the most job-relevant items lead. Emphasize keywords from the job description where they are already present in the resume. Minimal rewording — keep bullet phrasing nearly verbatim.
- BALANCED (default): Reorder bullets AND rephrase each bullet for clarity and impact. Adjust framing to match the job language while preserving every underlying fact. Same facts, different presentation.
- FULL: Reorder, rephrase, and restructure sections. You may combine two related bullets into one, or split an overloaded bullet into two. Maximize relevance while preserving ALL factual content from the original. You may NOT remove facts that would change what the candidate has done.

LOCKED FIELDS — copy these EXACTLY from the base resume, character-for-character, do NOT modify under any intensity:
- Candidate name
- Email address
- Phone number
- Physical address
- Job titles (e.g., "Senior Software Engineer")
- Company names (e.g., "Acme Corp")
- Employment dates (e.g., "2020-2023")
- Degree names, school names, graduation dates
- Certification names and issuing bodies

USE THE EXACT SECTION HEADINGS PROVIDED. The user message will give you the list of section headings that exist in the base resume (e.g., "Professional Summary", "Work Experience", "Skills", "Education"). Your JSON output MUST use these same heading strings verbatim so the downstream DOCX writer can map sections back to the template. Do not rename "Work Experience" to "Experience" or vice versa.

OUTPUT FORMAT — return ONLY valid JSON. No markdown fences, no prose, no explanation. The JSON must match this schema:

{
  "sections": [
    {
      "heading": "Professional Summary",
      "content": ["paragraph or bullet 1", "paragraph or bullet 2"]
    },
    {
      "heading": "Work Experience",
      "subsections": [
        {
          "company": "Acme Corp",
          "title": "Software Engineer",
          "dates": "2020-2023",
          "bullets": ["Tailored bullet 1", "Tailored bullet 2"]
        }
      ]
    }
  ],
  "skills": ["Python", "FastAPI"]
}

Notes on the schema:
- Use "content" (a list of strings) for simple sections like Summary, Education.
- Use "subsections" (a list of role dicts) for Work Experience. Each subsection MUST copy company/title/dates verbatim from the original.
- Top-level "skills" is optional — only include it if the base resume has a skills section.
- If the base resume has a section you don't recognize, include it with "content" as a list of strings.

Remember: the goal is to make the candidate's REAL experience look as relevant as possible to this specific job. Not to make up experience."""


VALIDATOR_SYSTEM_PROMPT = """You are a strict fact-checker for resume tailoring. Your job is to compare a TAILORED resume against the ORIGINAL (base) resume and flag any content in the tailored version that is not grounded in the original.

You will be given:
- ORIGINAL RESUME: the raw text of the candidate's real resume.
- TAILORED RESUME: a JSON object with a "sections" key containing the tailored content.

Flag any of the following as VIOLATIONS:

1. **invented_company**: A company name in the tailored resume that does not appear in the original.
2. **invented_title**: A job title that does not appear (or is materially different) in the original.
3. **invented_skill**: A skill or technology that is not in the original AND is not a reasonable inference from something that IS in the original.
4. **invented_metric**: A number, percentage, dollar figure, team size, or time-range that is not in the original.
5. **invented_credential**: A degree, certification, or school that is not in the original.
6. **modified_dates**: Employment dates (years, months) that differ from the original.
7. **modified_locked_field**: Any change to name, email, phone, or address.

DEFINITION OF "REASONABLY INFERABLE":
A skill is reasonably inferable if it is a direct superset, subset, or canonical alias of something in the original. Examples:

ACCEPTABLE (do NOT flag):
- Original says "FastAPI" → tailored says "Python backend development". (FastAPI is a Python web framework — fair inference.)
- Original says "PostgreSQL" → tailored says "SQL" or "relational databases".
- Original says "React" → tailored says "modern JavaScript UI frameworks".
- Original says "led a team of 4" → tailored says "team leadership".
- Original says "shipped feature X" → tailored says "delivered production features".

NOT ACCEPTABLE (flag as invented_skill):
- Original says "FastAPI" → tailored says "Django". (Different framework.)
- Original says "PostgreSQL" → tailored says "MongoDB". (Relational vs. document — different.)
- Original says "Python" → tailored says "Go". (Completely different language.)
- Original says "worked on backend" → tailored says "AWS". (Cloud provider not implied.)
- Original never mentions React → tailored adds "React" to skills list.

Paraphrasing and reordering are ALWAYS allowed. Do NOT flag rewording — only flag content that introduces new facts the candidate cannot back up.

OUTPUT FORMAT — return ONLY valid JSON, no markdown fences:

{
  "passed": true,
  "violations": []
}

Or on failure:

{
  "passed": false,
  "violations": [
    {
      "type": "invented_skill",
      "content": "React",
      "explanation": "Original resume does not mention React and it is not inferable from any technology that is mentioned."
    }
  ]
}

Set "passed" to false if there is at least one violation of types 1-7. Set "passed" to true if the only differences are rewording, reordering, or reasonable inferences."""


COVER_LETTER_SYSTEM_PROMPT = """You are a professional cover-letter writer. Write a concise, grounded cover letter (3-4 short paragraphs) for this specific job application.

STRUCTURE:
- Paragraph 1: Who the candidate is and why they are a fit for this specific role. One or two sentences. No "I am writing to apply for" — get straight to the fit.
- Paragraph 2: Two or three SPECIFIC highlights from the candidate's resume that map directly to the job. Name real projects, real technologies, real outcomes that are in the resume. Do not generalize.
- Paragraph 3: (Optional) One additional highlight if the role is complex enough to warrant it. Otherwise skip.
- Paragraph 4: Close with genuine enthusiasm for the company/role. One or two sentences. No fluff, no "I look forward to hearing from you" boilerplate.

CRITICAL RULE — EXTRACTIVE ONLY:
You may ONLY reference facts that are in the provided resume. Do NOT invent projects, technologies, metrics, or achievements. If the resume does not mention a specific technology the job asks for, do not claim the candidate has it. Pick the genuinely strongest real highlights and frame them well.

TONE:
- Professional but human. Not stiff.
- Confident, not desperate.
- Concrete, not buzzword-laden.
- No "I am passionate about" clichés. No "team player", "go-getter", "results-driven" filler.

LENGTH:
- Each paragraph: 2-4 sentences.
- Total: 3-4 paragraphs.
- No preamble like "Dear Hiring Manager" — return only the body paragraphs.

OUTPUT FORMAT — return ONLY valid JSON, no markdown fences:

{
  "paragraphs": [
    "Paragraph 1 text...",
    "Paragraph 2 text...",
    "Paragraph 3 text...",
    "Paragraph 4 text..."
  ]
}

The paragraphs list must have 3 or 4 entries. Each entry is a single paragraph string with no newlines inside."""


# ---------------------------------------------------------------------------
# Output schema (for documentation; engine does structural validation)
# ---------------------------------------------------------------------------

TAILORING_OUTPUT_SCHEMA = {
    "sections": [
        {
            "heading": "Professional Summary",  # exact heading from base resume
            "content": ["Line 1", "Line 2"],    # simple sections
        },
        {
            "heading": "Work Experience",
            "subsections": [
                {
                    "company": "Acme Corp",         # LOCKED — verbatim
                    "title": "Software Engineer",   # LOCKED — verbatim
                    "dates": "2020-2023",           # LOCKED — verbatim
                    "bullets": ["Tailored bullet 1", "Tailored bullet 2"],
                }
            ],
        },
    ],
    "skills": ["Python", "FastAPI"],  # optional top-level
}
"""Reference structure of the JSON returned by the tailoring LLM call.

The engine validates that ``sections`` is present and is a list; it does
not enforce a strict per-section schema (resumes vary). The DOCX writer
(``docx_writer.py``, Plan 04-04) does the final mapping back to the
template.
"""


# ---------------------------------------------------------------------------
# Escalation on retry
# ---------------------------------------------------------------------------

def get_escalated_prompt_suffix(retry: int) -> str:
    """Return an extra instruction appended to the user message on retry.

    The validator's strictness stays constant — only the TAILORING prompt
    gets more conservative each retry (research Pitfall 4). This keeps
    the judge stable while the candidate output tightens.
    """
    if retry <= 0:
        return ""
    if retry == 1:
        return (
            "\n\nIMPORTANT RETRY INSTRUCTION: The previous attempt was "
            "rejected by the fact-checker. Be MORE conservative this time. "
            "If you are in any doubt about whether a claim is grounded in "
            "the original resume, leave it out. Prefer near-verbatim "
            "rewording over creative framing."
        )
    # retry >= 2
    return (
        "\n\nFINAL RETRY — MAXIMUM CONSERVATISM: The previous two attempts "
        "were both rejected. This is the last chance. Only include bullet "
        "points that are near-verbatim from the original resume. Do NOT "
        "rephrase at all — you may ONLY reorder bullets and omit bullets "
        "that are not relevant. Every bullet you output must be traceable "
        "word-for-word to a bullet in the original."
    )


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

def build_system_messages(resume_sections_text: str) -> list[dict]:
    """Build the ``system`` content-block list for a tailoring call.

    The instructions block is NOT cached (short and stable anyway); the
    base-resume block IS cached via ``cache_control: ephemeral`` — this
    is the big one that benefits from the 5-minute cache window when
    multiple jobs are tailored in sequence. See research Pattern 2.
    """
    return [
        {
            "type": "text",
            "text": TAILORING_SYSTEM_PROMPT,
        },
        {
            "type": "text",
            "text": f"BASE RESUME:\n{resume_sections_text}",
            "cache_control": {"type": "ephemeral"},
        },
    ]


def build_tailoring_user_message(
    job_description: str,
    intensity: str,
    section_headings: list[str],
    retry: int = 0,
) -> str:
    """Format the per-job user message.

    We pass the exact section headings from the base resume (research
    Pitfall 5) so Claude uses matching names in the output JSON and the
    DOCX writer can map sections back cleanly.
    """
    intensity_norm = (intensity or "balanced").strip().lower()
    if intensity_norm not in ("light", "balanced", "full"):
        intensity_norm = "balanced"

    headings_block = ", ".join(f'"{h}"' for h in section_headings) or "(none)"

    body = (
        f"JOB DESCRIPTION:\n{job_description.strip()}\n\n"
        f"TAILORING INTENSITY: {intensity_norm}\n\n"
        f"BASE RESUME SECTION HEADINGS (use these verbatim in your output): "
        f"{headings_block}\n\n"
        "Tailor the base resume for this job following the instructions in "
        "the system prompt. Return only the JSON object."
    )
    return body + get_escalated_prompt_suffix(retry)


def build_tailoring_messages(
    job_description: str,
    intensity: str,
    section_headings: list[str],
    retry: int = 0,
) -> list[dict]:
    """Wrap :func:`build_tailoring_user_message` as a ``messages`` list."""
    return [
        {
            "role": "user",
            "content": build_tailoring_user_message(
                job_description=job_description,
                intensity=intensity,
                section_headings=section_headings,
                retry=retry,
            ),
        }
    ]


def build_validator_messages(
    original_text: str,
    tailored_json: str,
) -> tuple[list[dict], list[dict]]:
    """Return ``(system, messages)`` for a validator call.

    The validator does NOT use prompt caching — every call sees a
    different tailored output, and the original resume is small enough
    that caching the wrapper isn't worth the breakpoint budget.
    """
    system = [
        {"type": "text", "text": VALIDATOR_SYSTEM_PROMPT},
    ]
    user = (
        f"ORIGINAL RESUME:\n{original_text.strip()}\n\n"
        f"TAILORED RESUME (JSON):\n{tailored_json.strip()}\n\n"
        "Compare the tailored resume against the original and return the "
        "validator JSON object as specified in the system prompt."
    )
    messages = [{"role": "user", "content": user}]
    return system, messages


def build_cover_letter_messages(
    resume_text: str,
    job_description: str,
    company: str,
    title: str,
) -> tuple[list[dict], list[dict]]:
    """Return ``(system, messages)`` for a cover letter call.

    The resume text is cached (same rationale as tailoring — if the user
    applies to multiple jobs in a burst, the base resume prefix is
    stable). Job description, company, and title vary per call.
    """
    system = [
        {"type": "text", "text": COVER_LETTER_SYSTEM_PROMPT},
        {
            "type": "text",
            "text": f"CANDIDATE RESUME:\n{resume_text.strip()}",
            "cache_control": {"type": "ephemeral"},
        },
    ]
    user = (
        f"TARGET COMPANY: {company or '(unknown)'}\n"
        f"TARGET ROLE: {title or '(unknown)'}\n\n"
        f"JOB DESCRIPTION:\n{job_description.strip()}\n\n"
        "Write the cover letter as JSON following the schema in the system "
        "prompt. Return only the JSON object."
    )
    messages = [{"role": "user", "content": user}]
    return system, messages


__all__ = [
    "TAILORING_SYSTEM_PROMPT",
    "VALIDATOR_SYSTEM_PROMPT",
    "COVER_LETTER_SYSTEM_PROMPT",
    "TAILORING_OUTPUT_SCHEMA",
    "get_escalated_prompt_suffix",
    "build_system_messages",
    "build_tailoring_user_message",
    "build_tailoring_messages",
    "build_validator_messages",
    "build_cover_letter_messages",
]
