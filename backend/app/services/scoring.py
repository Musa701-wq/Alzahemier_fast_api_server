from datetime import datetime, timezone
from difflib import SequenceMatcher
import re
from typing import Any, Dict, List, Optional, Tuple
from backend.app.db.repository import db
from backend.app.models.schemas import ClockChecklist


def _fuzzy_word_match(candidate: str, target: str, threshold: float = 0.78) -> bool:
    c = candidate.strip().lower()
    t = target.strip().lower()
    if not c or not t:
        return False
    if c == t or t in c:
        return True
    return SequenceMatcher(None, c, t).ratio() >= threshold


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    cleaned = re.sub(r"[^\w\s\u0600-\u06FF]", " ", text.lower())
    return [tok.strip() for tok in cleaned.split() if tok.strip()]


def get_season_aliases(month: int) -> List[str]:
    if month in (12, 1, 2):
        return ["winter", "sardi", "sardiyan", "سردی", "موسم سرما"]
    if month in (3, 4):
        return ["spring", "bahaar", "bahar", "بہار"]
    if month in (5, 6, 7, 8, 9):
        return ["summer", "monsoon", "garmi", "garmiyan", "barsaat", "گرمی", "برسات"]
    return ["autumn", "fall", "khizaan", "khizan", "خزاں"]


def score_orientation(
    answers: Optional[Dict[str, Any]],
    raw_response: Optional[str],
    person_city: str,
    reference_dt: Optional[datetime] = None,
) -> Tuple[float, float, float, List[Dict[str, Any]]]:
    """
    Test 1 (Orientation): 1 point per correct answer (0 to 5), normalized to 0..100.
    Questions: day, date, month, season, city.
    """
    now = reference_dt or datetime.now(timezone.utc)
    points = 0.0
    markers: List[Dict[str, Any]] = []
    ans = answers or {}

    if not ans and raw_response:
        tokens = _tokenize(raw_response)
        # Fallback check against tokens if answers dict was not passed separately
        ans = {"raw_tokens": tokens}

    day_names_ur_en = {
        0: ["monday", "peer", "پیر"],
        1: ["tuesday", "mangal", "منگل"],
        2: ["wednesday", "budh", "بدھ"],
        3: ["thursday", "jumerat", "جمعرات"],
        4: ["friday", "jumma", "juma", "جمعہ"],
        5: ["saturday", "hafta", "ہفتہ"],
        6: ["sunday", "itwar", "اتوار"],
    }

    month_names_ur_en = {
        1: ["1", "01", "january", "jan", "جنوری"],
        2: ["2", "02", "february", "feb", "فروری"],
        3: ["3", "03", "march", "مارچ"],
        4: ["4", "04", "april", "اپریل"],
        5: ["5", "05", "may", "مئی"],
        6: ["6", "06", "june", "جون"],
        7: ["7", "07", "july", "جولائی"],
        8: ["8", "08", "august", "اگست"],
        9: ["9", "09", "september", "ستمبر"],
        10: ["10", "october", "اکتوبر"],
        11: ["11", "november", "نومبر"],
        12: ["12", "december", "دسمبر"],
    }

    # Explicit boolean or string checks
    if "correct_count" in ans and isinstance(ans["correct_count"], (int, float)):
        points = float(max(0, min(5, ans["correct_count"])))
    else:
        # 1. Day of week
        given_day = str(ans.get("day", "")).strip().lower()
        if given_day and any(_fuzzy_word_match(given_day, d) for d in day_names_ur_en[now.weekday()]):
            points += 1.0
        else:
            markers.append({"time_ms": 0, "label": "missed_day"})

        # 2. Date of month
        given_date = str(ans.get("date", "")).strip()
        if given_date and given_date == str(now.day):
            points += 1.0
        else:
            markers.append({"time_ms": 0, "label": "missed_date"})

        # 3. Month
        given_month = str(ans.get("month", "")).strip().lower()
        if given_month and any(_fuzzy_word_match(given_month, m) for m in month_names_ur_en[now.month]):
            points += 1.0
        else:
            markers.append({"time_ms": 0, "label": "missed_month"})

        # 4. Season
        given_season = str(ans.get("season", "")).strip().lower()
        if given_season and any(_fuzzy_word_match(given_season, s) for s in get_season_aliases(now.month)):
            points += 1.0
        else:
            markers.append({"time_ms": 0, "label": "missed_season"})

        # 5. City
        given_city = str(ans.get("city", "")).strip().lower()
        if given_city and _fuzzy_word_match(given_city, person_city.lower()):
            points += 1.0
        else:
            markers.append({"time_ms": 0, "label": "missed_city"})

    normalized = round((points / 5.0) * 100.0, 2)
    return normalized, points, 5.0, markers


def score_word_recall(
    transcript: str,
    item_bank_version: int = 1,
    custom_prompts: Optional[Dict[str, Any]] = None,
) -> Tuple[float, float, float, List[Dict[str, Any]]]:
    """
    Tests 2 & 7 (Immediate & Delayed Word Recall):
    1 point per word (0 to 5), fuzzy matching against dynamic session words or item bank.
    """
    banks = db.get_scoring_config("item_banks").get("versions", {})
    bank = banks.get(str(item_bank_version)) or banks.get("1", {})

    if custom_prompts and custom_prompts.get("words_en"):
        words_en = [str(w).lower() for w in custom_prompts.get("words_en", [])]
        words_ur = [str(w).lower() for w in custom_prompts.get("words_ur", [])]
        words_roman = [str(w).lower() for w in custom_prompts.get("words_roman_ur", [])]
    else:
        words_en = bank.get("words_en", [])
        words_ur = bank.get("words_ur", [])
        words_roman = bank.get("words_roman_ur", [])

    tokens = _tokenize(transcript)
    matched_indices = set()
    markers: List[Dict[str, Any]] = []

    for idx in range(len(words_en)):
        targets = []
        if idx < len(words_en):
            targets.append(words_en[idx])
        if idx < len(words_ur):
            targets.append(words_ur[idx])
        if idx < len(words_roman):
            targets.append(words_roman[idx])

        matched = False
        for tok in tokens:
            if any(_fuzzy_word_match(tok, tgt) for tgt in targets):
                matched = True
                break
        if matched:
            matched_indices.add(idx)
        else:
            missed_label = words_en[idx] if idx < len(words_en) else f"word_{idx + 1}"
            markers.append({"time_ms": 0, "label": f"missed_word:{missed_label}"})

    points = float(len(matched_indices))
    normalized = round((points / 5.0) * 100.0, 2)
    return normalized, points, 5.0, markers


def score_animal_naming(
    transcript: str,
    custom_prompts: Optional[Dict[str, Any]] = None,
) -> Tuple[float, float, float, List[Dict[str, Any]]]:
    """
    Test 3 (Verbal Category Fluency - 60s):
    Counts unique valid category items (animals + any dynamic category items from custom_prompts).
    15 or more items scores 10/10; fewer is scaled proportionally.
    """
    lex_cfg = db.get_scoring_config("animal_lexicon")
    target_max = float(lex_cfg.get("target_count_for_max_score", 15))
    valid_set = {a.lower() for a in lex_cfg.get("valid_animals", [])}
    if custom_prompts and custom_prompts.get("fluency_valid_items"):
        for item in custom_prompts["fluency_valid_items"]:
            if item:
                valid_set.add(str(item).strip().lower())
    valid_list = sorted(valid_set)

    tokens = _tokenize(transcript)
    unique_found: List[str] = []
    repeated_count = 0

    for tok in tokens:
        matched_canonical = None
        for valid_animal in valid_list:
            if _fuzzy_word_match(tok, valid_animal, threshold=0.84):
                matched_canonical = valid_animal
                break
        if matched_canonical:
            if matched_canonical in unique_found:
                repeated_count += 1
            else:
                unique_found.append(matched_canonical)

    count = len(unique_found)
    raw_points = min(10.0, round((count / target_max) * 10.0, 2))
    normalized = round((raw_points / 10.0) * 100.0, 2)
    markers = [{"time_ms": 0, "label": f"unique_animals:{count}"}]
    if repeated_count > 0:
        markers.append({"time_ms": 0, "label": f"repeated_animals:{repeated_count}"})
    return normalized, raw_points, 10.0, markers


def score_picture_story(
    transcript: str,
    item_bank_version: int = 1,
    timing: Optional[Dict[str, Any]] = None,
    custom_prompts: Optional[Dict[str, Any]] = None,
) -> Tuple[float, float, float, List[Dict[str, Any]]]:
    """
    Test 4 (Picture Story):
    Rule score 0 to 10 from distinct target items named (up to 6 pts),
    word count fluency (up to 4 pts), minus longest pause penalty from config.
    """
    rules = db.get_scoring_config("picture_story_rules")
    max_items_target = float(rules.get("max_items_target", 6))
    min_words_fluency = float(rules.get("min_words_for_full_fluency", 25))
    long_pause_ms = int(rules.get("long_pause_threshold_ms", 5000))
    pause_penalty = float(rules.get("pause_penalty_points", 2.0))

    banks = db.get_scoring_config("item_banks").get("versions", {})
    bank = banks.get(str(item_bank_version)) or banks.get("1", {})
    target_set = {t.lower() for t in bank.get("picture_target_items", [])}
    if custom_prompts and custom_prompts.get("picture_target_items"):
        for t in custom_prompts["picture_target_items"]:
            if t:
                target_set.add(str(t).strip().lower())
    target_items = sorted(target_set)

    tokens = _tokenize(transcript)
    word_count = len(tokens)

    named_items = set()
    for tok in tokens:
        for item in target_items:
            if _fuzzy_word_match(tok, item, threshold=0.82):
                named_items.add(item)

    item_points = min(6.0, (len(named_items) / max_items_target) * 6.0)
    fluency_points = min(4.0, (word_count / min_words_fluency) * 4.0)
    raw_points = item_points + fluency_points

    markers: List[Dict[str, Any]] = [
        {"time_ms": 0, "label": f"word_count:{word_count}"},
        {"time_ms": 0, "label": f"items_named:{len(named_items)}"},
    ]

    longest_pause = int((timing or {}).get("longest_pause_ms", 0))
    if longest_pause >= long_pause_ms:
        raw_points = max(0.0, raw_points - pause_penalty)
        markers.append({"time_ms": longest_pause, "label": f"long_pause_ms:{longest_pause}"})

    raw_points = round(min(10.0, raw_points), 2)
    normalized = round((raw_points / 10.0) * 100.0, 2)
    return normalized, raw_points, 10.0, markers


def score_clock_drawing(
    checklist: Optional[ClockChecklist],
) -> Tuple[float, float, float, List[Dict[str, Any]]]:
    """
    Test 5 (Clock Drawing):
    Score 0 to 10 from the 6-item checklist using weights in scoring_config.
    """
    weights = db.get_scoring_config("clock_drawing_rules").get(
        "weights",
        {
            "closed_circle": 1.5,
            "twelve_numbers": 2.0,
            "correct_order": 1.5,
            "correct_spacing": 1.5,
            "two_hands": 1.5,
            "hands_match_time": 2.0,
        },
    )
    chk = checklist or ClockChecklist()
    chk_dict = chk.model_dump()
    raw_points = 0.0
    markers: List[Dict[str, Any]] = []

    for field_name, weight in weights.items():
        if chk_dict.get(field_name, False):
            raw_points += float(weight)
        else:
            markers.append({"time_ms": 0, "label": f"clock_missing:{field_name}"})

    raw_points = round(min(10.0, raw_points), 2)
    normalized = round((raw_points / 10.0) * 100.0, 2)
    return normalized, raw_points, 10.0, markers


def score_dot_connecting(
    timing: Optional[Dict[str, Any]],
) -> Tuple[float, float, float, List[Dict[str, Any]]]:
    """
    Test 6 (Dot Connecting 1 to 12):
    Score 0 to 10 from completion time and error count against configured limits.
    """
    rules = db.get_scoring_config("dot_connecting_rules")
    optimal_sec = float(rules.get("optimal_time_seconds", 35.0))
    max_sec = float(rules.get("max_time_seconds", 120.0))
    penalty_per_error = float(rules.get("penalty_per_error", 1.5))

    t_data = timing or {}
    duration_sec = float(t_data.get("duration_seconds", optimal_sec))
    errors = int(t_data.get("errors", 0))
    completed_dots = int(t_data.get("completed_dots", 12))

    if completed_dots < 12:
        base_score = (completed_dots / 12.0) * 6.0
    elif duration_sec <= optimal_sec:
        base_score = 10.0
    elif duration_sec >= max_sec:
        base_score = 3.0
    else:
        ratio = (duration_sec - optimal_sec) / (max_sec - optimal_sec)
        base_score = 10.0 - (ratio * 6.0)

    raw_points = max(0.0, round(base_score - (errors * penalty_per_error), 2))
    normalized = round((raw_points / 10.0) * 100.0, 2)
    markers = [
        {"time_ms": int(duration_sec * 1000), "label": f"completion_sec:{round(duration_sec, 1)}"},
        {"time_ms": 0, "label": f"tap_errors:{errors}"},
    ]
    return normalized, raw_points, 10.0, markers


def compute_session_aggregates(results: List[Dict[str, Any]]) -> Tuple[float, Dict[str, float]]:
    """
    Computes the session total (average of normalized 0..100 test scores)
    and domain scores for orientation, memory, language, planning, and attention.
    """
    if not results:
        return 0.0, {}

    by_num = {r["test_number"]: float(r["score"]) for r in results}
    all_scores = list(by_num.values())
    total_score = round(sum(all_scores) / len(all_scores), 2)

    domain_Buckets: Dict[str, List[float]] = {
        "orientation": [],
        "memory": [],
        "language": [],
        "planning": [],
        "attention": [],
    }

    if 1 in by_num:
        domain_Buckets["orientation"].append(by_num[1])
    if 2 in by_num:
        domain_Buckets["memory"].append(by_num[2])
    if 7 in by_num:
        domain_Buckets["memory"].append(by_num[7])
    if 3 in by_num:
        domain_Buckets["language"].append(by_num[3])
    if 4 in by_num:
        domain_Buckets["language"].append(by_num[4])
    if 5 in by_num:
        domain_Buckets["planning"].append(by_num[5])
    if 6 in by_num:
        domain_Buckets["attention"].append(by_num[6])

    domain_scores = {
        dom: round(sum(vals) / len(vals), 2)
        for dom, vals in domain_Buckets.items()
        if vals
    }
    return total_score, domain_scores

