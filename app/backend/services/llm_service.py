"""
llm_service.py

Responsibilities (per specification section 14):
    - load the fixed system prompt,
    - select the correct internal prompt template,
    - inject only the required evidence from TransactionContext,
    - call Azure OpenAI,
    - return the generated text.

Nothing else. This module never reads CSV files, never retrains or executes
ML models, and never lets the LLM change a prediction or risk score -- it
only explains evidence already computed offline.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from app.backend.config import settings
from app.backend.security.validation import validate_request, ValidationError
from app.backend.services.transaction_service import TransactionContext
from app.backend.utils.cache import executive_summary_cache

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - exercised only when package missing
    OpenAI = None


# ---------------------------------------------------------------------------
# Paths / prompt loading
# ---------------------------------------------------------------------------

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

# Fixed question_id -> template filename mapping (spec section 20).
# The frontend NEVER sends raw prompt text -- only a question_id from this
# closed set, which is enforced upstream by security/validation.py.
QUESTION_TEMPLATE_MAP = {
    "question_1": "question_1_positive_shap.txt",
    "question_2": "question_2_gnn_neighbors.txt",
    "question_3": "question_3_negative_shap.txt",
}
INITIAL_ANALYSIS_TEMPLATE = "initial_analysis_prompt.txt"
SYSTEM_PROMPT_FILE = "system_prompt.txt"

# Per-template evidence whitelist. Each template only receives the fields it
# is allowed to see -- this is the enforcement point that prevents, e.g.,
# negative SHAP evidence leaking into the "positive SHAP" question answer.
TEMPLATE_REQUIRED_FIELDS = {
    "question_1_positive_shap.txt": [
        "transaction_id", "prediction", "risk_score",
        "positive_shap_features", "feature_categories",
    ],
    "question_2_gnn_neighbors.txt": [
        "transaction_id", "prediction", "risk_score", "gnn_importance",
        "important_neighbors", "important_edges", "selected_node",
    ],
    "question_3_negative_shap.txt": [
        "transaction_id", "prediction", "risk_score",
        "negative_shap_features", "feature_categories",
    ],
    "initial_analysis_prompt.txt": [
        "transaction_id", "prediction", "risk_score", "gnn_importance",
        "positive_shap_features", "negative_shap_features",
        "important_neighbors", "important_edges", "feature_categories",
    ],
}

_prompt_cache: Dict[str, str] = {}


def _load_prompt(filename: str) -> str:
    if filename not in _prompt_cache:
        path = os.path.join(PROMPTS_DIR, filename)
        with open(path, "r", encoding="utf-8") as f:
            _prompt_cache[filename] = f.read()
    return _prompt_cache[filename]


def _select_template(request_type: str, question_id: Optional[str]) -> str:
    if request_type == "initial_analysis":
        return INITIAL_ANALYSIS_TEMPLATE
    if request_type == "question":
        return QUESTION_TEMPLATE_MAP[question_id]
    # Unreachable if validate_request() was called first.
    raise ValidationError(
        reason_code="UNSUPPORTED_REQUEST_TYPE",
        message=f"Cannot select a template for request_type={request_type!r}.",
    )


def _build_evidence(template_file: str, context: TransactionContext) -> Dict[str, Any]:
    """Extract only the whitelisted subset of TransactionContext fields for
    the given template -- the data-leakage guard between question types."""
    allowed_fields = TEMPLATE_REQUIRED_FIELDS[template_file]
    context_dict = context.to_dict()
    return {field_name: context_dict.get(field_name) for field_name in allowed_fields}


def _render_template(template_text: str, evidence: Dict[str, Any]) -> str:
    # Missing placeholders render as an explicit "not supplied" marker rather
    # than raising, so a partially-available context still produces a safe,
    # honest prompt (system_prompt.txt rule 9: state when evidence is
    # unavailable).
    safe_evidence = {k: (v if v not in (None, "", []) else "not supplied") for k, v in evidence.items()}
    return template_text.format(**safe_evidence)


# ---------------------------------------------------------------------------
# Azure OpenAI call
# ---------------------------------------------------------------------------

def _get_azure_client() -> "OpenAI":
    """
    Build a standard OpenAI SDK client pointed at Azure's v1-compatible
    endpoint, per Azure OpenAI v1 API migration:
        base_url = https://<resource>.openai.azure.com/openai/v1/
    Configuration is sourced from config.settings (backed by .env), not
    read directly from os.environ here.
    """
    if OpenAI is None:
        raise RuntimeError(
            "The 'openai' package is required to call Azure OpenAI. "
            "Install it with: pip install openai"
        )
    endpoint = settings.AZURE_OPENAI_ENDPOINT
    api_key = settings.AZURE_OPENAI_KEY
    if not endpoint or not api_key:
        raise RuntimeError(
            "Azure OpenAI is not configured. Required .env values: "
            "AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, AZURE_OPENAI_DEPLOYMENT."
        )
    base_url = endpoint.rstrip("/") + "/openai/v1/"
    timeout_seconds = float(os.environ.get("AZURE_OPENAI_TIMEOUT_SECONDS", "60"))
    return OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds)


def _call_azure_openai_stream(system_prompt: str, task_prompt: str):
    """
    Streaming variant of _call_azure_openai. Yields text chunks as Azure
    produces them instead of blocking until the full answer is ready.

    Why this matters for perceived latency: per Microsoft's own guidance,
    streaming does not reduce total generation time, but it returns the
    first tokens in a fraction of the time, so the UI can show live text
    instead of a silent wait for the full 8-17s. This is the standard
    industry fix for reasoning-model latency (see Azure OpenAI latency docs).

    Yields:
        str chunks of the answer, in order. The caller is responsible for
        concatenating them for storage/caching.

    Raises:
        RuntimeError if the stream completes with no content at all (mirrors
        the empty-answer guard in the non-streaming path).
    """
    deployment = settings.AZURE_OPENAI_DEPLOYMENT
    if not deployment:
        raise RuntimeError("AZURE_OPENAI_DEPLOYMENT is not set in .env / config.py.")

    reasoning_effort = os.environ.get("AZURE_OPENAI_REASONING_EFFORT", "low")
    max_completion_tokens = int(os.environ.get("AZURE_OPENAI_MAX_COMPLETION_TOKENS", "2000"))

    client = _get_azure_client()
    stream = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_prompt},
        ],
        max_completion_tokens=max_completion_tokens,
        reasoning_effort=reasoning_effort,
        stream=True,
        stream_options={"include_usage": True},
    )

    total_chars = 0
    finish_reason = None
    for chunk in stream:
        if not chunk.choices:
            # The final usage-only chunk (from stream_options) has no choices.
            continue
        choice = chunk.choices[0]
        delta = getattr(choice.delta, "content", None)
        finish_reason = getattr(choice, "finish_reason", None) or finish_reason
        if delta:
            total_chars += len(delta)
            yield delta

    print(f"[LLM][stream] finish_reason={finish_reason} content_chars={total_chars} "
          f"budget={max_completion_tokens}")

    if total_chars == 0:
        raise RuntimeError(
            f"Azure returned an empty streamed answer (finish_reason={finish_reason}). "
            f"For a reasoning model this usually means max_completion_tokens "
            f"({max_completion_tokens}) is too low -- raise AZURE_OPENAI_MAX_COMPLETION_TOKENS "
            f"in .env, and/or set AZURE_OPENAI_REASONING_EFFORT=minimal."
        )


def _call_azure_openai(system_prompt: str, task_prompt: str) -> str:
    """
    Calls the configured Azure OpenAI deployment using GPT-5-compatible
    reasoning-model parameters (spec section 18):
        - max_completion_tokens (NOT max_tokens)
        - reasoning_effort
        - no temperature / top_p / frequency_penalty / presence_penalty

    The deployment name is read from config.settings (.env) and is never
    hardcoded into business logic.
    """
    deployment = settings.AZURE_OPENAI_DEPLOYMENT
    if not deployment:
        raise RuntimeError("AZURE_OPENAI_DEPLOYMENT is not set in .env / config.py.")

    reasoning_effort = os.environ.get("AZURE_OPENAI_REASONING_EFFORT", "low")
    # Reasoning models spend part of this budget on internal reasoning BEFORE
    # emitting the answer. Too small a value leaves no room for the answer and
    # Azure returns empty content. 2000 is a safe default; tune via .env.
    max_completion_tokens = int(os.environ.get("AZURE_OPENAI_MAX_COMPLETION_TOKENS", "2000"))

    client = _get_azure_client()
    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_prompt},
        ],
        max_completion_tokens=max_completion_tokens,
        reasoning_effort=reasoning_effort,
    )

    choice = response.choices[0]
    content = (choice.message.content or "").strip()
    finish_reason = getattr(choice, "finish_reason", None)

    # Diagnostic line (mirrors the [PERF] prints already visible in the terminal).
    usage = getattr(response, "usage", None)
    completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
    reasoning_tokens = None
    details = getattr(usage, "completion_tokens_details", None) if usage else None
    if details is not None:
        reasoning_tokens = getattr(details, "reasoning_tokens", None)
    print(
        f"[LLM] finish_reason={finish_reason} completion_tokens={completion_tokens} "
        f"reasoning_tokens={reasoning_tokens} content_chars={len(content)} "
        f"budget={max_completion_tokens}"
    )

    # Never silently return an empty answer. An empty/truncated response must
    # surface as an error instead of falling through to a stale prior answer.
    if not content:
        raise RuntimeError(
            f"Azure returned an empty answer (finish_reason={finish_reason}, "
            f"completion_tokens={completion_tokens}, reasoning_tokens={reasoning_tokens}). "
            f"For a reasoning model this usually means max_completion_tokens "
            f"({max_completion_tokens}) is too low -- raise AZURE_OPENAI_MAX_COMPLETION_TOKENS "
            f"in .env, and/or set AZURE_OPENAI_REASONING_EFFORT=minimal."
        )

    return content


def generate_explanation_stream(
    context: TransactionContext,
    request_type: str,
    question_id: Optional[str] = None,
    session_id: Optional[str] = None,
):
    """
    Streaming counterpart to generate_explanation(). Same validation, template
    selection, and evidence whitelisting -- only the Azure call and return
    shape differ.

    Yields:
        str chunks as they arrive from Azure. The caller should concatenate
        them to build up the displayed text incrementally (e.g. append to a
        placeholder in the UI on each chunk).

    On a cache hit (initial analysis with a cached executive summary), this
    yields the cached text as a single chunk immediately -- no Azure call.

    Caching behavior matches generate_explanation(): once the stream is fully
    consumed, the joined text is written to executive_summary_cache under the
    same conditions (initial_analysis + session_id provided). Callers that
    want caching MUST exhaust the generator (e.g. iterate it fully); caching
    happens as the last step after the final chunk is yielded.
    """
    validate_request(
        transaction_id=context.transaction_id,
        selected_node=context.selected_node,
        request_type=request_type,
        question_id=question_id,
    )

    use_summary_cache = request_type == "initial_analysis" and session_id is not None

    if request_type == "initial_analysis" and session_id is None:
        logger.warning(
            "Initial analysis (stream) called without session_id; cache will be skipped."
        )

    if use_summary_cache:
        cached = executive_summary_cache.get(session_id, context.transaction_id)
        if cached is not None:
            yield cached
            return

    template_file = _select_template(request_type, question_id)
    system_prompt = _load_prompt(SYSTEM_PROMPT_FILE)
    task_template = _load_prompt(template_file)

    evidence = _build_evidence(template_file, context)
    task_prompt = _render_template(task_template, evidence)

    chunks = []
    for delta in _call_azure_openai_stream(system_prompt, task_prompt):
        chunks.append(delta)
        yield delta

    if use_summary_cache:
        executive_summary_cache.set(session_id, context.transaction_id, "".join(chunks))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_explanation(
    context: TransactionContext,
    request_type: str,
    question_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """
    Generate an LLM explanation for a transaction.

    Args:
        context: A fully-built TransactionContext (see transaction_service.py).
        request_type: "initial_analysis" or "question".
        question_id: Required and validated when request_type == "question".
                     Must be one of QUESTION_TEMPLATE_MAP's keys.
        session_id: Optional. When provided together with
                     request_type == "initial_analysis", the generated text
                     ("Executive Summary") is cached for
                     utils.cache.DEFAULT_EXECUTIVE_SUMMARY_TTL_SECONDS so the
                     PDF report can reuse it without a second Azure call. If
                     omitted, caching is skipped entirely (used by the plain
                     Q1/Q2/Q3 question flow, which does not need reuse).

    Returns:
        The generated explanation text only (no raw API metadata).

    Raises:
        ValidationError: if the request fails validation. Azure is never
            called in this case.
    """
    validate_request(
        transaction_id=context.transaction_id,
        selected_node=context.selected_node,
        request_type=request_type,
        question_id=question_id,
    )

    use_summary_cache = request_type == "initial_analysis" and session_id is not None

    if request_type == "initial_analysis" and session_id is None:
        logger.warning(
            "Initial analysis called without session_id; cache will be skipped."
        )

    if use_summary_cache:
        cached = executive_summary_cache.get(session_id, context.transaction_id)
        if cached is not None:
            return cached

    template_file = _select_template(request_type, question_id)
    system_prompt = _load_prompt(SYSTEM_PROMPT_FILE)
    task_template = _load_prompt(template_file)

    evidence = _build_evidence(template_file, context)
    task_prompt = _render_template(task_template, evidence)

    result = _call_azure_openai(system_prompt, task_prompt)

    if use_summary_cache:
        executive_summary_cache.set(session_id, context.transaction_id, result)

    return result