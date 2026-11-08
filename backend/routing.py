"""Three-tier query classification: routes questions to SQL, VECTOR or HYBRID.

Tier 1: Rules (regex + keyword lists) — deterministic, cheap, catches high-confidence patterns.
Tier 2: Small classifier (pure-Python Naive Bayes) — trained on golden set + logged corrections.
Tier 3: LLM fallback via Generation provider — only for ambiguous cases; degrades to conservative VECTOR/SQL if provider unavailable.

All decisions are logged to `routing_log` for audit and future classifier training.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any

from .config import ROUTER_LLM_ENABLED
from .db import db
from .utils import is_catalog_overview, now_ms

ROUTE_SQL = "SQL"
ROUTE_VECTOR = "VECTOR"
ROUTE_HYBRID = "HYBRID"

MODEL_PATH = "router_model.json"


@dataclass
class RoutingDecision:
    route: str
    confidence: float
    tier: str
    reason: str
    intent: str | None = None


_CATALOG_SUBJECTS = re.compile(
    r"\b(documents?|docs?|files?|pdfs?|chunks?|pages?|corpus|catalog|library|indexes?|workspace)\b",
    re.IGNORECASE,
)

# Fuzzy variants for common typos. This list must stay limited to real
# catalog nouns: generic aggregate words won't do. Treating "many" or
# "number" as catalog subjects routed content questions such as "how many new
# parameters does IA3 introduce?" to the metadata branch, which answered with
# the document count instead of retrieved evidence.
_CATALOG_VARIANTS = re.compile(
    r"\b(chunks?|chunck?s?|chnk|chuncks|chuks)\b",
    re.IGNORECASE,
)

_CONTENT_MARKERS = re.compile(
    r"\b(mention|mentions|contain|contains|discuss|discusses|say|says|about|"
    r"explain|explains|summar|describ|compare|according|what\s+does|how\s+does|why\s+how)\w*\b",
    re.IGNORECASE,
)

_COMBINED_PATTERN = re.compile(
    r"\b(?:which|what|identify\s+the)\s+(?:document|documents|file|files|paper|papers|source|sources?)\b.*\b(?:what|how|say|says|ask|know|explain|describe|discuss)\b",
    re.IGNORECASE,
)

_AGGREGATE_WORDS = re.compile(
    r"\b(how\s+many|count|total|sum|average|mean|median|percentile|highest|lowest|most|fewest|least|"
    r"largest|smallest|biggest|rank(?:ed)?|top|first|ordered|sorted|"
    r"how\s+big|percentage|number|num|numbr?|numb|amt|amount|qty|quantity|mny|many)\b",
    re.IGNORECASE,
)

_LOOKUP_WORDS = re.compile(
    r"\b(list|show|find|which|what|name|names|status|indexed|uploaded|with|having|containing|all)\b",
    re.IGNORECASE,
)

_ID_PATTERN = re.compile(r"\b[a-zA-Z]{2,}-\d{4,}\b")

_STATUS_PATTERNS = re.compile(
    r"\b(not\s+indexed|synced|failed|processing|changed)\b",
    re.IGNORECASE,
)

_DATE_PATTERNS = re.compile(
    r"\b(uploaded|added|created|indexed)\s+(?:on|in|since|before|after)\b"
    r"|\bdocuments?\s+(?:from|in|during|since|before|after|for)\b"
    r"|\bmonths?\s+(?:in|of)\b"
    r"|\b(january|february|march|april|may|june|july|august|september|october|november|december)\b"
    r"|\blast\s+(day|week|month|year)\b"
    r"|\bthis\s+(day|week|month|year)\b"
    r"|\bsince\s+\d{4}-\d{2}-\d{2}\b"
    r"|\bbefore\s+\d{4}-\d{2}-\d{2}\b"
    r"|\bafter\s+\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)

_PER_DOC_SIZE = re.compile(r"\b(size|how\s+big)\s+(?:of|is)\s+[\w.\- ]+", re.IGNORECASE)


def classify_tier1(question: str) -> RoutingDecision | None:
    clean = question.strip()
    lower = question.casefold()

    if _COMBINED_PATTERN.search(clean):
        return RoutingDecision(
            route=ROUTE_HYBRID,
            confidence=0.90,
            tier="rules",
            reason="combined: 'which document... and what it says'",
            intent="combined",
        )

    if _ID_PATTERN.search(clean):
        return RoutingDecision(
            route=ROUTE_SQL,
            confidence=0.95,
            tier="rules",
            reason="exact document ID reference",
            intent="lookup",
        )

    if is_catalog_overview(clean):
        return RoutingDecision(
            route=ROUTE_SQL,
            confidence=0.88,
            tier="rules",
            reason="catalog overview request",
            intent="overview",
        )

    has_catalog = bool(_CATALOG_SUBJECTS.search(clean) or _CATALOG_VARIANTS.search(clean))
    has_aggregate = bool(_AGGREGATE_WORDS.search(clean))
    has_lookup = bool(_LOOKUP_WORDS.search(clean))
    has_status = bool(_STATUS_PATTERNS.search(clean))
    has_date = bool(_DATE_PATTERNS.search(clean))
    has_content = bool(_CONTENT_MARKERS.search(clean))

    if has_aggregate and has_catalog:
        if "size" in clean and "total" in clean:
            return RoutingDecision(
                route=ROUTE_SQL,
                confidence=0.90,
                tier="rules",
                reason="aggregate size query",
                intent="aggregate",
            )

    if _PER_DOC_SIZE.search(clean):
        return RoutingDecision(
            route=ROUTE_SQL,
            confidence=0.85,
            tier="rules",
            reason="per-document size query",
            intent="size_lookup",
        )

    # Special handling for size-related metadata queries
    size_metadata = re.search(r"\b(total\s+size|corpus\s+size|size\s+of\s+corpus)\b", lower)
    if size_metadata:
        return RoutingDecision(
            route=ROUTE_SQL,
            confidence=0.90,
            tier="rules",
            reason="corpus size metadata query",
            intent="aggregate",
        )

    structural_context = bool(
        re.search(
            r"\b(?:contain|containing|include|including|with|having)\b.{0,40}\b(?:tables?|figures?|images?)\b",
            lower,
        )
    )

    if has_content and not structural_context:
        return RoutingDecision(
            route=ROUTE_VECTOR,
            confidence=0.85,
            tier="rules",
            reason="content marker, non-structural",
            intent="narrative",
        )

    if has_aggregate and has_catalog:
        if structural_context:
            return RoutingDecision(
                route=ROUTE_HYBRID,
                confidence=0.85,
                tier="rules",
                reason="aggregate with structural filter (tables/figures)",
                intent="structured_aggregate",
            )
        return RoutingDecision(
            route=ROUTE_SQL,
            confidence=0.90 - 0.10 * has_aggregate / 3,
            tier="rules",
            reason="aggregate + catalog subject",
            intent="aggregate",
        )

    if has_lookup and has_catalog and not has_content:
        return RoutingDecision(
            route=ROUTE_SQL,
            confidence=0.75,
            tier="rules",
            reason="catalog lookup (list/show/find)",
            intent="lookup",
        )

    if has_status and has_catalog:
        return RoutingDecision(
            route=ROUTE_SQL,
            confidence=0.72,
            tier="rules",
            reason="catalog lookup with status filter",
            intent="status",
        )

    if has_date and has_catalog:
        return RoutingDecision(
            route=ROUTE_SQL,
            confidence=0.72,
            tier="rules",
            reason="catalog lookup with date filter",
            intent="temporal",
        )

    if has_aggregate and not has_catalog:
        return RoutingDecision(
            route=ROUTE_VECTOR,
            confidence=0.60,
            tier="rules",
            reason="aggregate without clear catalog subject → narrative",
            intent="ambiguous",
        )

    if has_catalog and (has_lookup or has_aggregate or has_status or has_date):
        return RoutingDecision(
            route=ROUTE_SQL,
            confidence=0.65,
            tier="rules",
            reason="catalog + metadata indicators",
            intent="metadata",
        )

    return RoutingDecision(
        route=ROUTE_VECTOR,
        confidence=0.50,
        tier="rules",
        reason="no clear signal; default to narrative",
        intent="default",
    )


def load_model() -> dict[str, Any] | None:
    model_file = os.environ.get("KNOWLEDGEOS_ROUTER_MODEL_PATH", "") or \
        os.path.join(os.environ.get("KNOWLEDGEOS_DATA_DIR", "data"), MODEL_PATH)
    try:
        with open(model_file, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _tokenize(text: str, vocab: set[str]) -> dict[str, int]:
    tokens = {}
    for word in text.casefold().split():
        if word in vocab:
            tokens[word] = tokens.get(word, 0) + 1
    return tokens


def classify_tier2(question: str, model: dict[str, Any]) -> RoutingDecision:
    vocab = set(model.get("vocab", []))
    priors = model.get("priori", {})
    likelihoods = model.get("likelihood", {})

    tokens = _tokenize(question, vocab)
    scores = {}
    for route in (ROUTE_SQL, ROUTE_VECTOR, ROUTE_HYBRID):
        log_prob = 0.0
        log_prior = priors.get(route, 0.0)
        for token, count in tokens.items():
            log_prob += count * likelihoods.get(route, {}).get(token, 0.0)
        scores[route] = log_prior + log_prob

    best_route = max(scores, key=scores.__getitem__)
    runner_up = max(score for route, score in scores.items() if route != best_route)
    conf = 1.0 / (1.0 + abs(scores[best_route] - runner_up))

    return RoutingDecision(
        route=best_route,
        confidence=min(conf, 0.90),
        tier="classifier",
        reason=f"nbayes score {scores[best_route]:.2f}",
        intent="nbayes",
    )


def llm_fallback_route(workspace_id: str, question: str) -> RoutingDecision | None:
    from .providers import choose_provider

    with db() as connection:
        row = choose_provider(connection, workspace_id, "Generation")
        if row is None:
            return None
    try:
        from .providers import provider_request
        resp = provider_request(
            dict(row),
            "/chat/completions",
            {
                "model": row["model"],
                "temperature": 0.0,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a query-router. Classify the question into exactly one of three categories: "
                            "SQL (catalog/aggregate questions about documents), VECTOR (semantic/narrative questions about content), "
                            "or HYBRID (combined: which document + what it says). Respond ONLY with JSON: "
                            '{"route": "SQL|VECTOR|HYBRID", "confidence": 0-1, "reason": "brief explanation"}.'
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Classify this question: {question}",
                    },
                ],
            },
            timeout=3.0,
        )
        msg = (resp.get("choices") or [{}])[0].get("message", {}).get("content", "")
        data = json.loads(re.search(r"\{.*\}", msg, re.DOTALL).group(0)) if re.search(r"\{.*\}", msg, re.DOTALL) else {}
        route = str(data.get("route", ROUTE_VECTOR)).upper()
        if route not in (ROUTE_SQL, ROUTE_VECTOR, ROUTE_HYBRID):
            route = ROUTE_VECTOR
        try:
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        return RoutingDecision(
            route=route,
            confidence=confidence,
            tier="llm",
            reason=data.get("reason", "llm fallback"),
        )
    except Exception:
        return None


def decide_route(
    workspace_id: str,
    question: str,
    use_llm: bool | None = None,
) -> tuple[RoutingDecision, int]:
    rule_decision = classify_tier1(question)

    model = load_model()

    tier2_decision = classify_tier2(question, model) if model else None

    # Tier 1 always returns a decision, but its low-confidence defaults are
    # guesses. Let the trained classifier replace only those weak guesses so a
    # high-confidence rule can never be overridden by tier 2.
    if (
        tier2_decision is not None
        and rule_decision.confidence < 0.60
        and tier2_decision.confidence > rule_decision.confidence
    ):
        final = tier2_decision
    else:
        final = rule_decision

    llm_route = None
    llm_enabled = ROUTER_LLM_ENABLED if use_llm is None else use_llm
    need_llm = llm_enabled and final.confidence < 0.55
    if need_llm:
        llm_route = llm_fallback_route(workspace_id, question)
        if llm_route:
            if final.route != llm_route.route:
                preferred_route = (
                    ROUTE_HYBRID
                    if ROUTE_HYBRID in (final.route, llm_route.route)
                    else max((final, llm_route), key=lambda decision: decision.confidence).route
                )
                final = RoutingDecision(
                    route=preferred_route,
                    confidence=min(final.confidence, llm_route.confidence) * 0.95,
                    tier="ensemble",
                    reason=f"disagreement: rules={final.route} vs llm={llm_route.route}",
                    intent="ensemble",
                )

    with db() as connection:
        routing_id = str(uuid.uuid4())
        connection.execute(
            "INSERT INTO routing_log (id, workspace_id, question, tier, rule_route, llm_route, "
            "route, confidence, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                routing_id,
                workspace_id,
                question,
                final.tier,
                rule_decision.route if rule_decision else None,
                llm_route.route if llm_route else None,
                final.route,
                final.confidence,
                final.reason,
                now_ms(),
            ),
        )

    return final, routing_id


def finalize_routing(routing_id: str, outcome: str, final_route: str | None = None) -> None:
    with db() as connection:
        update = {"outcome": outcome}
        if final_route:
            update["final_route"] = final_route
        set_clause = ", ".join(f"{k}=?" for k in update)
        connection.execute(
            f"UPDATE routing_log SET {set_clause}, updated_at=? WHERE id=?",
            [update[k] for k in update] + [now_ms(), routing_id],
        )


def train_from_golden(data_path: str, output_path: str | None = None) -> dict[str, Any]:
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"Golden set not found: {data_path}")

    routes = []
    docs_counts = {"SQL": 0, "VECTOR": 0, "HYBRID": 0}
    vocab = set()
    route_tokens: dict[str, dict[str, int]] = {r: {} for r in (ROUTE_SQL, ROUTE_VECTOR, ROUTE_HYBRID)}

    with open(data_path, "r") as f:
        for line in f:
            item = json.loads(line.strip())
            q = item.get("question", "")
            label = item.get("label", item.get("route", ""))
            if label not in docs_counts:
                continue
            docs_counts[label] += 1
            routes.append(label)
            for word in q.casefold().split():
                vocab.add(word)
                route_tokens[label][word] = route_tokens[label].get(word, 0) + 1

    total = sum(docs_counts.values())
    priors = {r: (c + 1) / (total + 3) for r, c in docs_counts.items()}

    likelihoods = {r: {} for r in (ROUTE_SQL, ROUTE_VECTOR, ROUTE_HYBRID)}
    vocab_list = list(vocab)
    for route in (ROUTE_SQL, ROUTE_VECTOR, ROUTE_HYBRID):
        route_word_count = sum(route_tokens[route].values())
        for word in vocab_list:
            likelihoods[route][word] = (route_tokens[route].get(word, 0) + 1) / (route_word_count + len(vocab))

    model = {"vocab": vocab_list, "priori": priors, "likelihood": likelihoods}

    if output_path:
        with open(output_path, "w") as f:
            json.dump(model, f)

    return model