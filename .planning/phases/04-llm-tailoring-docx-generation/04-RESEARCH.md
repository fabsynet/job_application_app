# Phase 4: LLM Tailoring & DOCX Generation - Research

**Researched:** 2026-04-12
**Domain:** Claude API integration, DOCX manipulation, hallucination validation, budget tracking
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Tailoring depth
- Three intensity levels: **Light** (reorder bullets, emphasize keywords), **Balanced** (reorder + rephrase, same facts different framing), **Full** (reorder, rephrase, restructure sections, combine/split bullets)
- Default for auto-discovered jobs: **Light rewrite** (Balanced)
- Configurable via a slider in Settings (global default) with per-job override available in the paste-a-link form and in the review queue before approval
- All sections editable by Claude (work experience, summary/objective, skills, education, etc.)
- **Locked fields (never modified regardless of intensity):** name, email, phone, address, job titles, company names, employment dates -- all factual/structural content

#### Hallucination guardrails
- **Semantic extractive** strictness: facts must be grounded in the base resume, but reasonable inferences are allowed (e.g., "FastAPI" in resume implies "Python backend development" is acceptable)
- **LLM-as-judge validator:** a second Claude call compares tailored output against the base resume and flags any invented content (companies, titles, skills, metrics not grounded in the original)
- On rejection: **auto-retry up to 3 times** with escalating strictness. If all 3 fail, skip the job and flag it in a "failed tailoring" queue for manual review
- **Validator findings visible in review queue:** when reviewing a tailored resume, show any validator warnings (e.g., "Retry 1: removed invented skill X"). Builds trust in the system

#### Budget & cost controls
- **Soft limit at 80% + hard halt at 100%:** warning banner appears at 80% budget, tailoring halts at 100%. Jobs stay in queue
- **Auto-resume:** tailoring resumes automatically when the user raises the budget cap OR a new month starts. No manual intervention required to restart
- **Per-job cost tracking:** read actual token counts from Claude API response headers. Each tailored resume shows tokens used and estimated cost
- **Dashboard running total:** monthly spend vs cap visible on dashboard with progress bar
- **Prompt caching:** aggressively cache the base resume + system prompt as a static prefix. Only the job description varies per call. Target ~50% cost reduction on repeated calls

#### Resume artifact handling
- **Versioned storage:** `data/resumes/{job_id}/v1.docx`, `v2.docx`, etc. Keeps retry history and full audit trail
- **Rendered HTML preview + download:** convert DOCX to HTML for in-browser preview, with a download button for the actual DOCX file
- **Side-by-side diff in review queue:** base resume on left, tailored on right, changed sections highlighted. Key for user trust
- **Full lineage:** each application record stores which base resume version was used, which tailored version, which job, and which prompt. Full reproducibility
- **Pixel-perfect format preservation:** use python-docx to read the base DOCX template, replace only text content, preserve all styles/fonts/spacing/margins exactly

#### Cover letter generation
- **Generate both resume and cover letter** for each tailored application
- **Tone:** Professional + concise -- 3-4 short paragraphs. Why you're a fit, 2-3 relevant highlights from resume, close with enthusiasm. No fluff
- Cover letter follows same hallucination guardrails (no invented facts)
- Cover letter stored alongside tailored resume in the versioned artifact directory

### Claude's Discretion
- Exact prompt design for the tailoring system prompt
- How to structure the LLM-as-judge validation prompt
- Cover letter template/structure details
- DOCX-to-HTML conversion library choice
- How to handle edge cases where base resume has unusual formatting

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope

</user_constraints>

## Summary

This phase integrates the Anthropic Claude API for resume tailoring and cover letter generation, with a multi-layer architecture: a provider-abstracted LLM client, a tailoring engine that produces structured JSON output, a hallucination validator (LLM-as-judge), DOCX generation preserving base resume formatting, budget enforcement, and artifact storage with HTML preview.

The existing codebase already has: python-docx 1.1.2 installed and used for resume text extraction (`app/resume/service.py`), Anthropic API key storage via FernetVault (`app/credentials/`), budget fields on the Settings model (`budget_cap_dollars`, `budget_spent_dollars`, `budget_month`), and the HTMX + Jinja2 + Pico.css UI pattern. The discovery pipeline (`app/discovery/pipeline.py`) provides an excellent template for how to structure the tailoring pipeline stage.

**Primary recommendation:** Use the Anthropic Python SDK (v0.94.0) directly with AsyncAnthropic for async calls, wrapped in a thin provider abstraction protocol. Use python-docx for format-preserving DOCX generation via run-level text replacement. Use mammoth (v1.12.0) for DOCX-to-HTML preview. Use structured JSON output from Claude for the tailoring response to enable programmatic section-by-section replacement.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| anthropic | 0.94.0 | Claude API client (AsyncAnthropic) | Official SDK, prompt caching support, token usage in response, async native |
| python-docx | 1.1.2 | DOCX read/write with format preservation | Already in project, run-level formatting access, current version is 1.2.0 but 1.1.2 works |
| mammoth | 1.12.0 | DOCX to HTML conversion for preview | Semantic HTML output, well-maintained, released Mar 2026 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | 24.4.0 | Structured logging (already installed) | All tailoring pipeline logging |
| httpx | 0.28.1 | HTTP client (already installed) | Only if bypassing SDK for raw API calls |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| anthropic SDK | litellm | Multi-provider but adds complexity; TAIL-02 only needs a protocol, not a full gateway |
| mammoth | python-docx HTML export | python-docx has no HTML export; mammoth is purpose-built |
| mammoth | pandoc subprocess | External binary dependency, harder to deploy in container |

**Installation:**
```bash
pip install anthropic==0.94.0 mammoth==1.12.0
```

Note: python-docx 1.1.2 is already installed. Consider upgrading to 1.2.0 if needed, but 1.1.2 has all required APIs.

## Architecture Patterns

### Recommended Project Structure
```
app/
  tailoring/
    __init__.py
    models.py          # TailoringRequest, TailoringResult, ValidationResult, CostRecord
    provider.py        # LLMProvider protocol + AnthropicProvider implementation
    prompts.py         # System prompts, tailoring prompts, validator prompts
    engine.py          # tailor_resume(), validate_output() -- orchestrates LLM calls
    budget.py          # BudgetGuard -- check/debit budget, month rollover
    docx_writer.py     # Write tailored content back into DOCX preserving formatting
    preview.py         # DOCX-to-HTML via mammoth, diff generation
    pipeline.py        # run_tailoring() -- pipeline stage called by scheduler
    service.py         # DB operations: save artifacts, query tailoring history
  web/
    routers/
      tailoring.py     # Review queue UI, preview, download endpoints
    templates/
      partials/
        tailoring_review.html.j2
        resume_preview.html.j2
        resume_diff.html.j2
        budget_widget.html.j2
data/
  resumes/
    base_resume.docx        # Existing base resume (Phase 2)
    {job_id}/
      v1.docx               # Tailored resume version 1
      v2.docx               # Retry version 2
      cover_letter_v1.docx  # Cover letter version 1
```

### Pattern 1: LLM Provider Protocol (TAIL-02)
**What:** Abstract LLM calls behind a Python Protocol so additional backends can be added later
**When to use:** All LLM interactions go through this abstraction
**Example:**
```python
from typing import Protocol, runtime_checkable
from dataclasses import dataclass

@dataclass
class LLMResponse:
    content: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    model: str

@runtime_checkable
class LLMProvider(Protocol):
    async def complete(
        self,
        system: list[dict],
        messages: list[dict],
        max_tokens: int,
        temperature: float = 0.3,
    ) -> LLMResponse: ...

class AnthropicProvider:
    """Concrete provider wrapping the Anthropic Python SDK."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5"):
        from anthropic import AsyncAnthropic
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(
        self,
        system: list[dict],
        messages: list[dict],
        max_tokens: int,
        temperature: float = 0.3,
    ) -> LLMResponse:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=messages,
        )
        usage = response.usage
        return LLMResponse(
            content=response.content[0].text,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_tokens=getattr(usage, 'cache_creation_input_tokens', 0) or 0,
            cache_read_tokens=getattr(usage, 'cache_read_input_tokens', 0) or 0,
            model=self._model,
        )
```

### Pattern 2: Prompt Caching for Cost Reduction (TAIL-07)
**What:** Cache the base resume + system prompt as a static prefix, vary only the job description
**When to use:** Every tailoring call
**Example:**
```python
# The system prompt + base resume text is the STATIC prefix (cached)
# The job description is the VARIABLE suffix (changes per call)

system_messages = [
    {
        "type": "text",
        "text": TAILORING_SYSTEM_PROMPT,  # instructions for tailoring
    },
    {
        "type": "text",
        "text": f"BASE RESUME:\n{resume_text}",
        "cache_control": {"type": "ephemeral"},  # Cache breakpoint here
    },
]

# User message varies per job -- NOT cached
messages = [
    {
        "role": "user",
        "content": f"JOB DESCRIPTION:\n{job_description}\n\nTAILORING INTENSITY: {intensity}",
    }
]
```
**Key detail:** Minimum 1024 tokens for Sonnet 4.5, 2048 for Sonnet 4.6, 4096 for Opus. The system prompt + resume will easily exceed this. Cache TTL is 5 minutes (default) -- sufficient since tailoring jobs run sequentially in a pipeline.

### Pattern 3: Structured JSON Output for Tailoring
**What:** Claude returns a structured JSON object with sections, so we can map them back to DOCX paragraphs
**When to use:** The tailoring prompt requests JSON output
**Example:**
```python
# Prompt instructs Claude to return JSON with this structure:
TAILORING_OUTPUT_SCHEMA = {
    "sections": [
        {
            "heading": "Professional Summary",
            "content": ["Bullet point 1", "Bullet point 2"],
        },
        {
            "heading": "Work Experience",
            "subsections": [
                {
                    "company": "Acme Corp",  # LOCKED -- copied verbatim
                    "title": "Software Engineer",  # LOCKED
                    "dates": "2020-2023",  # LOCKED
                    "bullets": ["Tailored bullet 1", "Tailored bullet 2"],
                }
            ],
        },
    ],
    "skills": ["Python", "FastAPI", "..."],
}
```

### Pattern 4: Run-Level DOCX Text Replacement (TAIL-05)
**What:** Replace paragraph text at the run level to preserve all character formatting
**When to use:** Writing tailored content back into the DOCX template
**Example:**
```python
from docx import Document
from copy import deepcopy

def replace_paragraph_text_preserving_format(paragraph, new_text: str):
    """Replace paragraph text while preserving run-level formatting.

    Strategy: Keep the first run's formatting, clear all runs,
    set the first run's text to the new content.
    """
    if not paragraph.runs:
        paragraph.text = new_text
        return

    # Preserve first run's formatting as the template
    first_run = paragraph.runs[0]

    # Clear all runs except the first
    for run in paragraph.runs[1:]:
        run._element.getparent().remove(run._element)

    # Set the first run's text (preserves its font, bold, italic, etc.)
    first_run.text = new_text


def build_tailored_docx(base_path: str, tailored_sections: dict, output_path: str):
    """Create a tailored DOCX by modifying a copy of the base resume.

    Opens the base DOCX, walks paragraphs by heading, replaces content
    from the tailored_sections dict while preserving all formatting.
    """
    doc = Document(base_path)

    current_heading = None
    section_map = {s["heading"]: s for s in tailored_sections["sections"]}

    for para in doc.paragraphs:
        style_name = para.style.name if para.style else ""

        if style_name.startswith("Heading"):
            current_heading = para.text.strip()
            continue

        if current_heading and current_heading in section_map:
            # Replace content based on the tailored section
            # (actual implementation maps bullets to paragraphs)
            pass

    doc.save(output_path)
```

### Pattern 5: LLM-as-Judge Validation (TAIL-04)
**What:** A second Claude call validates the tailored output against the base resume
**When to use:** After every tailoring call, before saving the artifact
**Example:**
```python
VALIDATOR_SYSTEM_PROMPT = """You are a strict fact-checker for resume tailoring.
Compare the TAILORED resume against the ORIGINAL resume.

Flag ANY of the following as violations:
1. Companies not in the original
2. Job titles not in the original
3. Skills/technologies not reasonably inferable from the original
4. Metrics/numbers not in the original
5. Degrees or certifications not in the original

"Reasonably inferable" means: if the original says "FastAPI", then
"Python backend development" is acceptable. But "React" is NOT acceptable
unless explicitly stated.

Return JSON:
{
  "passed": true/false,
  "violations": [
    {"type": "invented_skill", "content": "React", "explanation": "Not in original resume"}
  ]
}
"""
```

### Pattern 6: Budget Guard (TAIL-08)
**What:** Check budget before each tailoring call, debit after completion
**When to use:** Wraps every LLM call
**Example:**
```python
from datetime import datetime

class BudgetGuard:
    """Enforce monthly LLM budget limits.

    Uses the existing Settings.budget_cap_dollars, budget_spent_dollars,
    and budget_month fields.
    """

    @staticmethod
    def estimate_cost(input_tokens: int, output_tokens: int,
                      cache_read_tokens: int = 0, cache_write_tokens: int = 0,
                      model: str = "claude-sonnet-4-5") -> float:
        """Estimate cost in dollars from token counts."""
        # Sonnet 4.5 pricing (example -- verify current pricing)
        # Input: $3/MTok, Output: $15/MTok, Cache read: $0.30/MTok
        PRICING = {
            "claude-sonnet-4-5": {
                "input": 3.0, "output": 15.0,
                "cache_read": 0.30, "cache_write": 3.75,
            },
        }
        rates = PRICING.get(model, PRICING["claude-sonnet-4-5"])
        cost = (
            (input_tokens * rates["input"] / 1_000_000)
            + (output_tokens * rates["output"] / 1_000_000)
            + (cache_read_tokens * rates["cache_read"] / 1_000_000)
            + (cache_write_tokens * rates["cache_write"] / 1_000_000)
        )
        return round(cost, 6)

    @staticmethod
    async def check_budget(session) -> tuple[bool, float, float]:
        """Returns (can_proceed, spent, cap). Handles month rollover."""
        from app.settings.service import get_settings_row
        settings = await get_settings_row(session)

        current_month = datetime.utcnow().strftime("%Y-%m")
        if settings.budget_month != current_month:
            # New month -- reset spend
            settings.budget_spent_dollars = 0.0
            settings.budget_month = current_month

        cap = settings.budget_cap_dollars
        spent = settings.budget_spent_dollars

        if cap <= 0:  # No cap set
            return (True, spent, cap)

        return (spent < cap, spent, cap)
```

### Anti-Patterns to Avoid
- **Paragraph.text setter for replacement:** Destroys all run-level formatting (bold, italic, font). Always work at the run level.
- **Sending full PII to Claude:** Only send content sections (bullets, skills, summary). Strip name, email, phone, address from the LLM prompt. The Profile model has these fields separately -- do NOT include them.
- **Single giant prompt:** Split tailoring and validation into separate calls. Trying to self-validate in the same call is unreliable.
- **Hardcoded pricing:** Store pricing as configuration, not constants. Claude model pricing changes.
- **Blocking LLM calls:** Always use AsyncAnthropic. The existing app is fully async.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DOCX manipulation | Custom XML parsing of .docx | python-docx 1.1.2+ | OOXML spec is enormous; python-docx handles styles, runs, fonts, tables |
| DOCX to HTML | Custom DOCX->HTML converter | mammoth 1.12.0 | Handles heading mapping, list nesting, image extraction, style conversion |
| Claude API integration | Raw httpx calls to /v1/messages | anthropic SDK 0.94.0 | Handles auth, retries, streaming, token counting, prompt caching natively |
| Token cost estimation | Manual token counting | SDK's response.usage fields | SDK returns exact input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens |
| Budget month rollover | Custom cron job | Check-on-access in BudgetGuard | Settings.budget_month already exists; compare to current month on each check |
| Text diffing for review UI | Custom diff algorithm | Python difflib or Jinja2 template logic | Section-by-section comparison is simpler than full text diff for resumes |

**Key insight:** The DOCX format-preservation problem is the hardest part of this phase. python-docx's run-level API handles it, but the mapping from Claude's JSON output back to specific DOCX paragraphs requires careful section-matching logic. Do not try to regenerate the DOCX from scratch -- always modify a copy of the base template.

## Common Pitfalls

### Pitfall 1: Paragraph.text Setter Destroys Formatting
**What goes wrong:** Using `paragraph.text = "new text"` replaces all runs with a single plain run, losing bold, italic, font settings.
**Why it happens:** The .text setter is a convenience method that creates a new single run.
**How to avoid:** Always work at the run level. Clear extra runs, then set `runs[0].text = "new text"` to preserve the first run's formatting.
**Warning signs:** Tailored DOCX has all-uniform formatting, losing the base resume's visual structure.

### Pitfall 2: Prompt Caching Below Minimum Token Threshold
**What goes wrong:** Cache breakpoints are silently ignored if the content before the breakpoint is below the minimum token count.
**Why it happens:** Claude Sonnet 4.5 requires 1024 tokens minimum before cache breakpoint. Short system prompts won't cache.
**How to avoid:** Place the cache breakpoint AFTER the system prompt AND the full base resume text. A typical resume is 500-2000 tokens, plus a system prompt of 200-500 tokens -- should exceed the minimum for Sonnet 4.5 (1024). Verify by checking `response.usage.cache_creation_input_tokens > 0` on the first call.
**Warning signs:** `cache_read_input_tokens` is always 0 across multiple calls.

### Pitfall 3: PII Leaking into LLM Prompts (SAFE-04)
**What goes wrong:** Name, email, phone, address end up in Claude API call logs or the prompt itself.
**Why it happens:** Using the full resume text without stripping PII sections.
**How to avoid:** The existing `extract_resume_text()` returns sections by heading. Strip PII-containing sections (typically the header/contact section) before sending to Claude. The Profile model already stores PII separately. Only send work experience bullets, skills, education content, and summary text.
**Warning signs:** Check LLM prompt logs for PII patterns. The existing log scrubber will catch API keys but may not catch names/emails unless registered.

### Pitfall 4: Hallucination Validation False Positives
**What goes wrong:** The LLM-as-judge rejects valid rephrasing as hallucination, causing all 3 retries to fail.
**Why it happens:** The validator prompt is too strict, treating reasonable inferences as violations.
**How to avoid:** The prompt must explicitly define "reasonably inferable" with examples. Track rejection rates -- if >20% of jobs fail all retries, the validator prompt needs loosening. The escalating strictness on retries should increase the TAILORING prompt's conservatism, not the validator's.
**Warning signs:** High rate of jobs ending up in the "failed tailoring" queue.

### Pitfall 5: DOCX Section Matching Failures
**What goes wrong:** Claude's JSON output has section headings that don't exactly match the DOCX paragraph headings, causing content to be placed in wrong sections or lost.
**Why it happens:** Resume headings vary ("Work Experience" vs "Professional Experience" vs "Experience").
**How to avoid:** Include the exact section headings from the base resume in the tailoring prompt. Instruct Claude to use the SAME heading names. Add fuzzy matching as a fallback (e.g., Levenshtein distance or keyword-based matching for "experience", "education", "skills").
**Warning signs:** Tailored DOCX is missing sections or has duplicated content.

### Pitfall 6: Race Condition on Budget Updates
**What goes wrong:** Two concurrent tailoring calls both check budget, both proceed, both spend, exceeding the cap.
**Why it happens:** The app runs with --workers 1 (single-process), but the async event loop could interleave two tailoring coroutines.
**How to avoid:** Use a simple asyncio.Lock around budget check + debit. Since the app is single-worker, this is sufficient. No need for database-level locking.
**Warning signs:** budget_spent_dollars exceeds budget_cap_dollars.

## Code Examples

### Anthropic SDK Async Call with Prompt Caching
```python
# Source: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
from anthropic import AsyncAnthropic

client = AsyncAnthropic(api_key="...")

response = await client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=4096,
    temperature=0.3,
    system=[
        {
            "type": "text",
            "text": "You are a professional resume tailoring assistant...",
        },
        {
            "type": "text",
            "text": f"BASE RESUME CONTENT:\n{resume_sections_text}",
            "cache_control": {"type": "ephemeral"},
        },
    ],
    messages=[
        {
            "role": "user",
            "content": f"Tailor this resume for the following job:\n\n{job_description}",
        }
    ],
)

# Token usage from response
print(response.usage.input_tokens)                  # Non-cached input tokens
print(response.usage.output_tokens)                  # Output tokens
print(response.usage.cache_creation_input_tokens)    # First call: tokens written to cache
print(response.usage.cache_read_input_tokens)        # Subsequent calls: tokens read from cache
```

### DOCX Format-Preserving Write
```python
# Source: python-docx docs + community patterns
from docx import Document
from pathlib import Path
import shutil

def create_tailored_docx(
    base_resume_path: Path,
    output_path: Path,
    tailored_sections: dict,
) -> Path:
    """Create a tailored DOCX by modifying a copy of the base resume.

    Preserves all formatting by working at the run level.
    """
    # Copy the base file first -- never modify the original
    shutil.copy2(base_resume_path, output_path)
    doc = Document(str(output_path))

    current_heading = None
    section_map = {s["heading"].lower(): s for s in tailored_sections.get("sections", [])}

    for para in doc.paragraphs:
        style_name = para.style.name if para.style else ""
        text = para.text.strip()

        if style_name.startswith("Heading"):
            current_heading = text.lower()
            continue

        if not text:
            continue

        # Find matching tailored content for this section
        if current_heading and current_heading in section_map:
            section = section_map[current_heading]
            # Replace logic depends on section structure
            # (bullets list, subsections with company/title/bullets, etc.)
            pass

    doc.save(str(output_path))
    return output_path
```

### Mammoth DOCX to HTML Preview
```python
# Source: https://pypi.org/project/mammoth/
import mammoth
from pathlib import Path

def docx_to_html(docx_path: Path) -> str:
    """Convert a DOCX file to HTML for in-browser preview."""
    with open(docx_path, "rb") as f:
        result = mammoth.convert_to_html(f)
    html = result.value       # The generated HTML
    warnings = result.messages  # Any conversion warnings
    return html
```

### New Database Models
```python
# New models for app/tailoring/models.py (SQLModel)
from sqlmodel import Field, SQLModel
from sqlalchemy import Column, JSON
from typing import Optional
from datetime import datetime

class TailoringRecord(SQLModel, table=True):
    """Tracks each tailoring attempt for a job."""
    __tablename__ = "tailoring_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    version: int = Field(default=1)
    intensity: str = Field(default="balanced")  # light | balanced | full
    status: str = Field(default="pending")  # pending | completed | failed | rejected
    base_resume_path: str = Field()
    tailored_resume_path: Optional[str] = Field(default=None)
    cover_letter_path: Optional[str] = Field(default=None)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    cache_read_tokens: int = Field(default=0)
    cache_write_tokens: int = Field(default=0)
    estimated_cost_dollars: float = Field(default=0.0)
    validation_passed: Optional[bool] = Field(default=None)
    validation_warnings: str = Field(default="")  # JSON string of warnings
    retry_count: int = Field(default=0)
    prompt_hash: Optional[str] = Field(default=None)  # For reproducibility
    created_at: datetime = Field(default_factory=datetime.utcnow)

class CostLedger(SQLModel, table=True):
    """Per-call cost tracking for budget enforcement."""
    __tablename__ = "cost_ledger"

    id: Optional[int] = Field(default=None, primary_key=True)
    tailoring_record_id: Optional[int] = Field(default=None, foreign_key="tailoring_records.id")
    call_type: str = Field()  # tailor | validate | cover_letter
    model: str = Field()
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    cache_read_tokens: int = Field(default=0)
    cache_write_tokens: int = Field(default=0)
    cost_dollars: float = Field(default=0.0)
    month: str = Field(index=True)  # "2026-04"
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| anthropic SDK manual cache_control per message | Top-level `cache_control` param for auto-caching | Feb 2026 | Simpler API -- one param instead of per-message breakpoints |
| Organization-level cache isolation | Workspace-level cache isolation | Feb 5, 2026 | No impact for single-user app |
| python-docx 1.1.x | python-docx 1.2.0 available | Recent | Minor improvements; 1.1.2 is sufficient |

**Deprecated/outdated:**
- The older `anthropic-version: 2023-06-01` header used in the existing validation code should be updated for newer features
- Do not use the OpenAI compatibility endpoint (`/v1/chat/completions`) -- prompt caching is NOT supported through it

## Open Questions

1. **Claude model choice for tailoring vs validation**
   - What we know: Sonnet 4.5 is cost-effective ($3/$15 per MTok), Haiku is cheaper but lower quality
   - What's unclear: Whether Haiku is sufficient for the validator (simpler task than tailoring)
   - Recommendation: Use Sonnet 4.5 for tailoring, test Haiku for validation. Make model configurable per call type. Start with Sonnet for both to ensure quality

2. **Exact DOCX section mapping strategy**
   - What we know: Base resume sections are extracted by Heading styles (already implemented in `extract_resume_text`)
   - What's unclear: How to handle resumes without Heading styles (all plain text), or with non-standard heading usage
   - Recommendation: Fall back to paragraph-order matching if no headings found. Log a warning. The user uploaded the base resume, so it should be well-structured

3. **Cover letter DOCX template**
   - What we know: Cover letter needs to be a DOCX file stored alongside the resume
   - What's unclear: Whether to use a separate DOCX template or generate from scratch
   - Recommendation: Generate cover letter DOCX from scratch using python-docx with a standard business letter layout (matching the base resume's font family if detectable). Simpler than maintaining a template

4. **ATS-friendly output checks (TAIL-06)**
   - What we know: Requirement says "no tables, standard fonts, keyword coverage reported"
   - What's unclear: Exact ATS compatibility rules
   - Recommendation: Post-generation check that verifies: no Table elements in DOCX, font is in a standard ATS set (Arial, Calibri, Times New Roman, etc.), keyword overlap percentage between job description and tailored resume

## Sources

### Primary (HIGH confidence)
- Anthropic Claude prompt caching docs: https://platform.claude.com/docs/en/build-with-claude/prompt-caching -- cache_control syntax, pricing, minimum tokens, usage response fields
- Anthropic Python SDK: https://github.com/anthropics/anthropic-sdk-python -- v0.94.0, AsyncAnthropic, response.usage
- python-docx docs: https://python-docx.readthedocs.io/en/latest/ -- run-level formatting, paragraph/run API, styles
- mammoth PyPI: https://pypi.org/project/mammoth/ -- v1.12.0, DOCX to HTML conversion

### Secondary (MEDIUM confidence)
- python-docx community patterns for text replacement: https://github.com/python-openxml/python-docx/issues/415
- Anthropic pricing page: https://platform.claude.com/docs/en/about-claude/pricing
- LiteLLM for provider abstraction: https://docs.litellm.ai/docs/providers/anthropic (decided against for simplicity)

### Tertiary (LOW confidence)
- ATS compatibility rules -- based on general industry knowledge, no authoritative single source
- Hallucination detection patterns -- synthesized from multiple research papers, not a specific library

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- anthropic SDK, python-docx, mammoth all verified with official sources
- Architecture: HIGH -- patterns follow existing codebase conventions (pipeline.py, service.py, models.py)
- Pitfalls: MEDIUM -- DOCX formatting pitfall is well-documented; hallucination validation tuning is experience-based
- Budget/caching: HIGH -- verified with official Anthropic docs, token usage fields confirmed

**Research date:** 2026-04-12
**Valid until:** 2026-05-12 (30 days -- stable libraries, Anthropic SDK may have minor updates)
