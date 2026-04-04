"""Search and ranking logic for fuzzy and non-fuzzy matching."""

import re

from rapidfuzz import fuzz

# Split identifiers on CamelCase boundaries, underscores, colons, and hyphens
_SEGMENT_RE = re.compile(r"[_:\-]+|(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# Role-based score adjustments applied to the base tier score
_ROLE_SCORE_ADJUST = {
    "function": 4,
    "type": 1,
    "enum": -3,
    "macro": 0,
    "enumerator": -8,
    "data": -3,
    "label": -10,
    "": -5,
}


def _tokenize_name(name):
    """Split an identifier into lowercase segments.

    >>> _tokenize_name('cutensornetTensorSVD')
    ['cutensornet', 'tensor', 'svd']
    >>> _tokenize_name('CUTENSOR_ALGO_SVD')
    ['cutensor', 'algo', 'svd']
    >>> _tokenize_name('cudaMemcpy')
    ['cuda', 'memcpy']
    """
    return [s.lower() for s in _SEGMENT_RE.split(name) if s]


def _score_entry(query, target, segments=None):
    """Score a query term against a target name using tiered matching.

    Tiers (base score before role adjustment):
      100 — full exact match (case-insensitive)
       97 — query matches a segment exactly
       94 — a segment starts with query
       88 — query is a substring of the full name
      ≤82 — rapidfuzz partial_ratio (capped)

    Args:
        query: Search term (will be lowercased)
        target: Candidate name (will be lowercased)
        segments: Pre-computed segments from _tokenize_name, or None
    """
    q = query.lower()
    t = target.lower()

    # For Doxygen signatures like "cudaFree ( void* devPtr )", extract the
    # bare name before lowering so CamelCase segmentation works correctly.
    bare_raw = target.split("(")[0].split(" (")[0].strip()
    bare = bare_raw.lower()

    if q == t or q == bare:
        return 100.0

    if segments is None:
        segments = _tokenize_name(target)

    # Tokenize the original-case bare name for accurate segment splitting
    bare_segments = _tokenize_name(bare_raw) if bare != t else segments

    for seg in bare_segments:
        if q == seg:
            return 97.0

    for seg in bare_segments:
        if seg.startswith(q):
            return 94.0

    if q in t or q in bare:
        return 88.0

    return min(fuzz.partial_ratio(q, t), 82.0)


def _parse_query_groups(keywords):
    """Split keyword tokens into OR-groups of AND-terms (fzf-subset syntax).

    Handles both shell-separated tokens and quoted strings:
      ['SVD', 'QR']        -> [['SVD', 'QR']]            # AND
      ['SVD', '|', 'QR']   -> [['SVD'], ['QR']]           # OR
      ['SVD | QR']          -> [['SVD'], ['QR']]           # OR (quoted)
      ['a', 'b', '|', 'c'] -> [['a', 'b'], ['c']]         # (a AND b) OR c
    """
    all_tokens = " ".join(keywords).split()
    groups = []
    current = []
    for token in all_tokens:
        if token == "|":
            if current:
                groups.append(current)
            current = []
        else:
            current.append(token)
    if current:
        groups.append(current)
    return [g for g in groups if g]


def filter_groups(groups, keywords, use_fuzzy=False, threshold=60.0):
    if not keywords:
        return groups

    query_groups = _parse_query_groups(keywords)
    if not query_groups:
        return []

    if use_fuzzy:
        segments_cache = [_tokenize_name(g["group"]) for g in groups]

        best_matches = {}
        for index, g in enumerate(groups):
            role = g.get("role", "")
            adjust = _ROLE_SCORE_ADJUST.get(role, 0)

            best_group_score = None
            best_group_terms = None

            for or_group in query_groups:
                # AND: entry must pass threshold for every term in the group
                term_scores = []
                for term in or_group:
                    base = _score_entry(term, g["group"], segments_cache[index])
                    # Threshold on text-match quality only (before role adjust)
                    if base < threshold:
                        break
                    term_scores.append(base)
                else:
                    # All terms matched — score is min (weakest link)
                    group_score = min(term_scores)
                    # Apply role adjustment for ranking only
                    ranked_score = max(0.0, min(group_score + adjust, 100.0))
                    if best_group_score is None or ranked_score > best_group_score:
                        best_group_score = ranked_score
                        best_group_terms = or_group

            if best_group_score is not None:
                key = g["url"]
                if (
                    key not in best_matches
                    or best_group_score > best_matches[key]["score"]
                ):
                    item_copy = g.copy()
                    item_copy["score"] = best_group_score
                    item_copy["matched_keyword"] = ",".join(best_group_terms)
                    best_matches[key] = item_copy

        filtered = list(best_matches.values())
        filtered.sort(key=lambda x: -x["score"])
        return filtered

    # Non-fuzzy fallback with AND/OR
    filtered = []
    seen = set()
    for or_group in query_groups:
        for g in groups:
            key = g.get("url", id(g))
            if key in seen:
                continue
            name_lower = g["group"].lower()
            if all(term.lower() in name_lower for term in or_group):
                filtered.append(g)
                seen.add(key)

    return filtered
