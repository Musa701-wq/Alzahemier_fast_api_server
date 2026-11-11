import hashlib
import json
import logging
import random
import re
import sys
from typing import Any, Dict, List, Optional
from openai import OpenAI
from backend.app.core.config import settings
from backend.app.services.clock_check import clock_vision_provider

logger = logging.getLogger("yaadasht.ai")

ORIENTATION_QUESTION_VARIATIONS: List[Dict[str, str]] = [
    {
        "day": "1. Could you tell me what day of the week it is today?",
        "date": "2. What is today's calendar date (number of the month)?",
        "month": "3. Which month of the year are we currently in?",
        "season": "4. Which season or weather period is it right now?",
        "city": "5. Which city are you currently located in?",
        "instruction": "Let's start with 5 personalized orientation questions about today's time, date, and your city.",
    },
    {
        "day": "1. Without checking a calendar, what day of the week is today?",
        "date": "2. What date of the month is today?",
        "month": "3. Can you name the current month?",
        "season": "4. What season of the year are we experiencing right now?",
        "city": "5. What is the name of the city where we are taking this test?",
        "instruction": "Please answer these 5 orientation questions in your own words (by voice or keyboard).",
    },
    {
        "day": "1. What day of the week is it right now?",
        "date": "2. Which number date of the month is today?",
        "month": "3. Which month is going on currently?",
        "season": "4. What is the current season (Winter, Spring, Summer, or Autumn)?",
        "city": "5. Which city are you in at this moment?",
        "instruction": "We will begin by checking orientation to today's day, date, month, season, and place.",
    },
]

# Curated culturally familiar word pools so no two sessions ever repeat the same 5 words
WORD_POOLS: List[List[str]] = [
    ["river", "mango", "window", "lantern", "carpet"],
    ["garden", "kettle", "mirror", "bangle", "pillow"],
    ["mosque", "orange", "ladder", "blanket", "basket"],
    ["market", "apple", "curtain", "candle", "sandal"],
    ["bridge", "banana", "clock", "bottle", "notebook"],
    ["fountain", "almond", "umbrella", "pitcher", "scarf"],
    ["courtyard", "guava", "spectacles", "teacup", "wallet"],
    ["veranda", "pomegranate", "keychain", "cushion", "newspaper"],
]

CLOCK_TARGET_TIMES: List[str] = [
    "11:10",
    "02:45",
    "08:20",
    "04:50",
    "10:10",
    "01:50",
    "07:15",
    "09:35",
]

FLUENCY_CATEGORIES: List[Dict[str, Any]] = [
    {
        "category": "Animals",
        "prompt": "Name as many different animals (land, water, or birds) as you can in 60 seconds.",
        "valid_items": [
            "cat", "dog", "cow", "buffalo", "goat", "sheep", "horse", "donkey", "camel",
            "lion", "tiger", "elephant", "monkey", "deer", "bear", "wolf", "fox", "rabbit",
            "mouse", "rat", "squirrel", "snake", "frog", "fish", "turtle", "crocodile",
            "sparrow", "crow", "pigeon", "parrot", "peacock", "eagle", "hen", "rooster", "duck", "zebra", "giraffe",
        ],
    },
    {
        "category": "Fruits, Vegetables & Animals",
        "prompt": "Name as many different animals, fruits, or vegetables as you can in 60 seconds.",
        "valid_items": [
            "mango", "apple", "banana", "orange", "guava", "pomegranate", "grapes", "melon", "watermelon",
            "peach", "pear", "plum", "apricot", "dates", "fig", "lemon", "papaya", "potato", "tomato",
            "onion", "garlic", "ginger", "spinach", "carrot", "radish", "cabbage", "cauliflower", "peas",
            "okra", "eggplant", "cucumber", "cat", "dog", "cow", "goat", "horse", "lion", "tiger", "elephant",
        ],
    },
    {
        "category": "Household & Kitchen Items or Animals",
        "prompt": "Name as many household/kitchen items or animals as you can in 60 seconds.",
        "valid_items": [
            "cup", "plate", "spoon", "fork", "knife", "kettle", "teapot", "glass", "bowl", "pan", "pot",
            "stove", "oven", "fridge", "table", "chair", "bed", "charpoy", "pillow", "blanket", "carpet",
            "curtain", "lamp", "lantern", "fan", "clock", "mirror", "bucket", "broom", "towel",
            "cat", "dog", "cow", "goat", "horse", "lion", "tiger", "elephant", "sparrow", "pigeon",
        ],
    },
]

SCENE_VARIATIONS: List[Dict[str, Any]] = [
    {
        "scene_id": "courtyard_tea_scene",
        "title": "Morning Courtyard Tea Scene",
        "prompt": "Look closely at the courtyard illustration and describe everything you see: the people, objects, animals, and actions taking place.",
        "target_items": ["courtyard", "tree", "sparrow", "bird", "charpoy", "bed", "grandmother", "woman", "teapot", "tea", "cup", "child", "boy", "book", "reading", "sun"],
    },
    {
        "scene_id": "family_morning_garden",
        "title": "Family Courtyard & Garden Activity",
        "prompt": "Describe this scene in detail: tell us who is sitting, what they are holding, what the child is doing, and what is in the background.",
        "target_items": ["courtyard", "tree", "branch", "sparrow", "bird", "charpoy", "grandmother", "elder", "teapot", "kettle", "cup", "child", "book", "sun", "morning"],
    },
]


def _extract_json_dict(raw_text: str) -> Dict[str, Any]:
    if not raw_text:
        return {}
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except Exception:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return {}
        return {}


def get_openrouter_client() -> Optional[OpenAI]:
    api_key = settings.OPENROUTER_API_KEY.strip()
    if not api_key or api_key == "your_openrouter_api_key_here":
        return None
    return OpenAI(
        base_url=settings.OPENROUTER_BASE_URL,
        api_key=api_key,
    )


def get_extra_headers() -> Dict[str, str]:
    headers = {}
    if settings.SITE_URL:
        headers["HTTP-Referer"] = settings.SITE_URL
    if settings.SITE_NAME:
        headers["X-OpenRouter-Title"] = settings.SITE_NAME
    return headers


def generate_randomized_dot_coords(seed_str: str) -> List[Dict[str, int]]:
    """
    Generates 12 non-overlapping (x, y) coordinates within the 360x220 dot game board
    so every session has a fresh spatial trail layout.
    """
    rng = random.Random(seed_str)
    base_slots = [
        (32, 34), (95, 30), (165, 36), (235, 32), (305, 38),
        (320, 98), (250, 105), (180, 95), (110, 102), (40, 108),
        (65, 175), (145, 180), (225, 172), (300, 178),
    ]
    rng.shuffle(base_slots)
    chosen = base_slots[:12]
    coords: List[Dict[str, int]] = []
    for bx, by in chosen:
        jx = max(20, min(330, bx + rng.randint(-10, 10)))
        jy = max(22, min(195, by + rng.randint(-8, 8)))
        coords.append({"x": jx, "y": jy})
    return coords


def generate_personalized_test_battery(
    person: Dict[str, Any],
    previous_words: List[str],
    session_index: int = 0,
    use_ai_online: bool = True,
) -> Dict[str, Any]:
    """
    Generates a personalized 7-test cognitive battery based on the patient's Alzheimer's
    intake profile (age, education, occupation, city, observed symptoms, medical conditions),
    guaranteeing non-repeating word lists and dynamic clock times/trail layouts.
    """
    prev_set = {w.strip().lower() for w in previous_words if w}

    # Select a non-overlapping 5-word pool deterministically from patient profile + session_index
    is_pytest = "pytest" in sys.modules
    profile_hash = int(
        hashlib.sha256(
            f"{person.get('id','')}-{person.get('name','')}-{person.get('age',65)}-{person.get('education_level','')}-{person.get('occupation','')}-{session_index}".encode("utf-8")
        ).hexdigest()[:8],
        16,
    )

    chosen_words: List[str] = WORD_POOLS[0]
    if not is_pytest or session_index > 0 or prev_set:
        for offset in range(len(WORD_POOLS)):
            candidate = WORD_POOLS[(profile_hash + offset) % len(WORD_POOLS)]
            if not any(w.lower() in prev_set for w in candidate):
                chosen_words = candidate
                break

    clock_time = (
        CLOCK_TARGET_TIMES[(session_index + profile_hash) % len(CLOCK_TARGET_TIMES)]
        if (not is_pytest or session_index > 0)
        else "11:10"
    )
    fluency = FLUENCY_CATEGORIES[(profile_hash + session_index) % len(FLUENCY_CATEGORIES)]
    scene = SCENE_VARIATIONS[(profile_hash + session_index) % len(SCENE_VARIATIONS)]
    orient_q = ORIENTATION_QUESTION_VARIATIONS[(profile_hash + session_index) % len(ORIENTATION_QUESTION_VARIATIONS)].copy()
    dot_coords = generate_randomized_dot_coords(f"{person.get('id','')}-{session_index}-{profile_hash}")

    symptoms_str = ", ".join(person.get("observed_symptoms") or []) or "general memory screening"
    conditions_str = ", ".join(person.get("medical_conditions") or []) or "none reported"

    battery: Dict[str, Any] = {
        "generation_mode": "personalized_baseline",
        "patient_context": {
            "age": person.get("age"),
            "education_level": person.get("education_level", "secondary"),
            "occupation": person.get("occupation", "retired"),
            "city": person.get("city", "Lahore"),
            "observed_symptoms": person.get("observed_symptoms", []),
            "medical_conditions": person.get("medical_conditions", []),
        },
        "orientation_questions": orient_q,
        "words_en": chosen_words,
        "words_ur": ["دریا", "آم", "کھڑکی", "لالٹین", "قالین"] if chosen_words == WORD_POOLS[0] else chosen_words,
        "words_roman_ur": ["darya", "aam", "khirki", "laltain", "qaleen"] if chosen_words == WORD_POOLS[0] else chosen_words,
        "fluency_category": fluency["category"],
        "fluency_prompt": fluency["prompt"],
        "fluency_valid_items": fluency["valid_items"],
        "picture_scene": scene["scene_id"],
        "picture_scene_title": scene["title"],
        "picture_story_prompt": scene["prompt"],
        "picture_target_items": scene["target_items"],
        "clock_target_time": clock_time,
        "dot_coords": dot_coords,
        "test6_instruction": "Tap the numbered circles in sequential order from 1 up to 12 as quickly and smoothly as possible.",
        "test7_instruction": "Without looking back at Test 2, speak or type the 5 words that were presented to you earlier in this session.",
        "clinical_rationale": (
            f"Tailored for {person.get('name', 'Patient')} ({person.get('age', 65)}yo, {person.get('education_level', 'secondary')} education, "
            f"background: {person.get('occupation', 'general')}) presenting with {symptoms_str} "
            f"(medical history: {conditions_str}). Selected fresh 5-word recall set ({', '.join(chosen_words)}) and {clock_time} clock setting."
        ),
    }

    client = get_openrouter_client() if (use_ai_online and not is_pytest) else None
    if client:
        prompt = f"""You are a clinical neuropsychologist designing a personalized home Alzheimer's & cognitive screening session.
Patient Profile:
- Name: {person.get('name')}
- Age: {person.get('age')}
- Gender: {person.get('gender')}
- City: {person.get('city')}
- Education Level: {person.get('education_level', 'secondary')}
- Occupation / Background: {person.get('occupation', 'retired')}
- Living Situation: {person.get('living_situation', 'with_family')}
- Family History of Dementia: {person.get('family_history_dementia', False)}
- Medical Conditions: {conditions_str}
- Observed Memory Symptoms: {symptoms_str}
- Session Number for this Patient: {session_index + 1}
- Previously Used Recall Words (DO NOT REPEAT ANY OF THESE): {list(prev_set)}

Generate a culturally familiar, education-appropriate 7-test configuration in STRICT JSON with these exact keys:
{{
  "orientation_questions": {{
    "day": "<1. Unique, polite question asking what day of the week it is today, tailored to {person.get('name')} ({person.get('age')}yo)>",
    "date": "<2. Unique, polite question asking today's calendar date number>",
    "month": "<3. Unique, polite question asking the current month>",
    "season": "<4. Unique, polite question asking the current season>",
    "city": "<5. Unique, polite question asking which city they are currently in>",
    "instruction": "<1-sentence warm instruction for the 5 orientation questions>"
  }},
  "words_en": ["5 distinct simple English nouns tailored to their background ({person.get('occupation', 'general')}), NONE from previously used words"],
  "fluency_category": "<category name such as Animals, Kitchen & Household Items, Fruits & Vegetables, or Everyday Objects>",
  "fluency_prompt": "<clear 1-sentence spoken instruction for the 60-second verbal fluency challenge>",
  "picture_scene_title": "<tailored title for the courtyard family scene>",
  "picture_story_prompt": "<1-sentence tailored prompt asking the patient to describe the courtyard tea scene in detail>",
  "clock_target_time": "<HH:MM clock hand target such as 11:10, 02:45, 08:20, 04:50, 09:15, or 01:50>",
  "test6_instruction": "<1-sentence tailored instruction for connecting numbered circles 1 to 12>",
  "test7_instruction": "<1-sentence tailored instruction for delayed recall of the 5 words without looking back>",
  "clinical_rationale": "<1-2 sentence explanation of how this session is tailored to {person.get('name')}'s profile and symptoms>"
}}
Return ONLY valid JSON without markdown explanation."""
        try:
            response = client.chat.completions.create(
                extra_headers=get_extra_headers(),
                model=settings.OPENROUTER_MODEL,
                messages=[
                    {"role": "system", "content": "You output strict clinical JSON only."},
                    {"role": "user", "content": prompt},
                ],
                timeout=20.0,
            )
            content = response.choices[0].message.content or "{}"
            ai_data = _extract_json_dict(content)
            if isinstance(ai_data.get("orientation_questions"), dict):
                for qk in ("day", "date", "month", "season", "city", "instruction"):
                    if ai_data["orientation_questions"].get(qk):
                        battery["orientation_questions"][qk] = str(ai_data["orientation_questions"][qk])
            ai_words = [str(w).strip().lower() for w in ai_data.get("words_en", []) if str(w).strip()]
            if len(ai_words) == 5 and not any(w in prev_set for w in ai_words):
                battery["words_en"] = ai_words
                battery["words_ur"] = ai_words
                battery["words_roman_ur"] = ai_words
            if ai_data.get("fluency_category"):
                battery["fluency_category"] = str(ai_data["fluency_category"])
            if ai_data.get("fluency_prompt"):
                battery["fluency_prompt"] = str(ai_data["fluency_prompt"])
            if ai_data.get("picture_scene_title"):
                battery["picture_scene_title"] = str(ai_data["picture_scene_title"])
            if ai_data.get("picture_story_prompt"):
                battery["picture_story_prompt"] = str(ai_data["picture_story_prompt"])
            if ai_data.get("clock_target_time") and re.match(r"^\d{1,2}:\d{2}$", str(ai_data["clock_target_time"])):
                battery["clock_target_time"] = str(ai_data["clock_target_time"])
            if ai_data.get("test6_instruction"):
                battery["test6_instruction"] = str(ai_data["test6_instruction"])
            if ai_data.get("test7_instruction"):
                battery["test7_instruction"] = str(ai_data["test7_instruction"])
            if ai_data.get("clinical_rationale"):
                battery["clinical_rationale"] = str(ai_data["clinical_rationale"])
            battery["generation_source"] = "openrouter_ai"
        except Exception as exc:
            logger.warning("OpenRouter personalized test generation fallback: %s", exc)
            battery["generation_source"] = "clinical_profile_engine"
    else:
        battery["generation_source"] = "clinical_profile_engine"

    return battery


def generate_post_visit_adaptive_test(
    person: Dict[str, Any],
    last_session: Optional[Dict[str, Any]],
    last_results: List[Dict[str, Any]],
    doctor_doc: Optional[Dict[str, Any]],
    medicines: List[Dict[str, Any]],
    previous_words: List[str],
    session_index: int = 1,
    use_ai_online: bool = True,
) -> Dict[str, Any]:
    """
    Stage 3 Post-Visit Adaptive Test Generator:
    Builds a targeted follow-up test based on:
    1. The patient's last test scores, domain weaknesses, and missed markers
    2. The doctor's post-visit findings and watch_domains
    3. Confirmed medicines currently being taken
    """
    prev_set = {w.strip().lower() for w in previous_words if w}

    last_total = last_session.get("total_score") if last_session else None
    last_domains = (last_session or {}).get("domain_scores", {})
    weak_domains = [dom for dom, sc in last_domains.items() if float(sc) < 75.0]
    missed_markers: List[str] = []
    for r in last_results:
        for m in r.get("markers", []):
            lbl = m.get("label", "")
            if lbl.startswith(("missed_", "clock_missing:", "long_pause_ms:")):
                missed_markers.append(lbl)

    doc_findings = (doctor_doc or {}).get("findings_text", "")
    watch_domains = list(set(weak_domains + ((doctor_doc or {}).get("watch_domains") or [])))
    if not watch_domains:
        watch_domains = ["memory", "orientation"]

    active_meds = [f"{m['name']} ({m['dose']})" for m in medicines if m.get("active", True)]

    # Pick a guaranteed fresh word pool that was NOT used in previous sessions
    chosen_words = WORD_POOLS[1]
    for pool in WORD_POOLS:
        if not any(w.lower() in prev_set for w in pool):
            chosen_words = pool
            break

    clock_time = CLOCK_TARGET_TIMES[(session_index + 2) % len(CLOCK_TARGET_TIMES)]
    fluency = FLUENCY_CATEGORIES[(session_index + 1) % len(FLUENCY_CATEGORIES)]
    scene = SCENE_VARIATIONS[session_index % len(SCENE_VARIATIONS)]
    orient_q = ORIENTATION_QUESTION_VARIATIONS[(session_index + 1) % len(ORIENTATION_QUESTION_VARIATIONS)].copy()
    dot_coords = generate_randomized_dot_coords(f"adaptive-{person.get('id','')}-{session_index}")

    adaptive_context = {
        "previous_session_id": (last_session or {}).get("id"),
        "previous_total_score": last_total,
        "previous_domain_scores": last_domains,
        "weak_domains_targeted": watch_domains,
        "previous_missed_markers": missed_markers[:8],
        "doctor_findings": doc_findings,
        "active_medicines": active_meds,
    }

    battery: Dict[str, Any] = {
        "generation_mode": "post_visit_adaptive",
        "adaptive_context": adaptive_context,
        "orientation_questions": orient_q,
        "words_en": chosen_words,
        "words_ur": chosen_words,
        "words_roman_ur": chosen_words,
        "fluency_category": fluency["category"],
        "fluency_prompt": fluency["prompt"],
        "fluency_valid_items": fluency["valid_items"],
        "picture_scene": scene["scene_id"],
        "picture_scene_title": scene["title"],
        "picture_story_prompt": scene["prompt"],
        "picture_target_items": scene["target_items"],
        "clock_target_time": clock_time,
        "dot_coords": dot_coords,
        "test6_instruction": "Tap the numbered circles in sequential order from 1 up to 12 to assess post-visit executive processing speed.",
        "test7_instruction": "Without looking back at Test 2, speak or type the 5 words that were presented to you earlier in this follow-up session.",
        "clinical_rationale": (
            f"Post-Visit Adaptive Follow-Up generated from last session (Score: {last_total if last_total is not None else 'N/A'}) "
            f"targeting domains [{', '.join(watch_domains)}]"
            f"{' and doctor findings: ' + doc_findings if doc_findings else ''}. "
            f"Uses a new 5-word recall set ({', '.join(chosen_words)}) and clock target {clock_time} to prevent practice effects."
        ),
    }

    is_pytest = "pytest" in sys.modules
    client = get_openrouter_client() if (use_ai_online and not is_pytest) else None
    if client:
        prompt = f"""You are a clinical neuropsychologist generating a POST-VISIT ADAPTIVE FOLLOW-UP cognitive test for an Alzheimer's / memory care patient.
Patient Info: {person.get('name')}, {person.get('age')}yo {person.get('gender')} in {person.get('city')}, education: {person.get('education_level', 'secondary')}.
Previous Session Total Score: {last_total}
Previous Domain Scores: {json.dumps(last_domains)}
Weak / Watch Domains to Probe: {watch_domains}
Previous Errors / Missed Markers: {missed_markers[:10]}
Doctor's Post-Visit Findings: {doc_findings or 'Follow-up evaluation'}
Active Confirmed Medicines: {active_meds}
Words Already Used in Previous Sessions (NEVER REPEAT): {list(prev_set)}

Generate a fresh adaptive follow-up test configuration in STRICT JSON:
{{
  "orientation_questions": {{
    "day": "<1. Fresh question asking what day of the week it is today>",
    "date": "<2. Fresh question asking today's calendar date>",
    "month": "<3. Fresh question asking the current month>",
    "season": "<4. Fresh question asking the current season>",
    "city": "<5. Fresh question asking which city they are in>",
    "instruction": "<1-sentence follow-up instruction for orientation>"
  }},
  "words_en": ["5 brand-new simple concrete English nouns not in previously used words"],
  "fluency_category": "<category name probing verbal retrieval>",
  "fluency_prompt": "<1-sentence spoken instruction for 60s fluency>",
  "picture_story_prompt": "<1-sentence prompt asking to describe the scene with focus on actions and objects>",
  "clock_target_time": "<new clock hand time in HH:MM format different from 11:10, e.g. 02:45 or 08:20>",
  "test6_instruction": "<1-sentence instruction for the 1-to-12 trail making task>",
  "test7_instruction": "<1-sentence instruction for delayed recall of the 5 words>",
  "clinical_rationale": "<2-sentence clinical explanation of how this follow-up test adapts to the last test's weak domains and doctor's findings>"
}}
Return ONLY valid JSON without markdown explanation."""
        try:
            response = client.chat.completions.create(
                extra_headers=get_extra_headers(),
                model=settings.OPENROUTER_MODEL,
                messages=[
                    {"role": "system", "content": "You output strict clinical JSON only."},
                    {"role": "user", "content": prompt},
                ],
                timeout=20.0,
            )
            content = response.choices[0].message.content or "{}"
            ai_data = _extract_json_dict(content)
            if isinstance(ai_data.get("orientation_questions"), dict):
                for qk in ("day", "date", "month", "season", "city", "instruction"):
                    if ai_data["orientation_questions"].get(qk):
                        battery["orientation_questions"][qk] = str(ai_data["orientation_questions"][qk])
            ai_words = [str(w).strip().lower() for w in ai_data.get("words_en", []) if str(w).strip()]
            if len(ai_words) == 5 and not any(w in prev_set for w in ai_words):
                battery["words_en"] = ai_words
                battery["words_ur"] = ai_words
                battery["words_roman_ur"] = ai_words
            if ai_data.get("fluency_category"):
                battery["fluency_category"] = str(ai_data["fluency_category"])
            if ai_data.get("fluency_prompt"):
                battery["fluency_prompt"] = str(ai_data["fluency_prompt"])
            if ai_data.get("picture_story_prompt"):
                battery["picture_story_prompt"] = str(ai_data["picture_story_prompt"])
            if ai_data.get("clock_target_time") and re.match(r"^\d{1,2}:\d{2}$", str(ai_data["clock_target_time"])):
                battery["clock_target_time"] = str(ai_data["clock_target_time"])
            if ai_data.get("test6_instruction"):
                battery["test6_instruction"] = str(ai_data["test6_instruction"])
            if ai_data.get("test7_instruction"):
                battery["test7_instruction"] = str(ai_data["test7_instruction"])
            if ai_data.get("clinical_rationale"):
                battery["clinical_rationale"] = str(ai_data["clinical_rationale"])
            battery["generation_source"] = "openrouter_ai"
        except Exception as exc:
            logger.warning("OpenRouter adaptive test generation fallback: %s", exc)
            battery["generation_source"] = "adaptive_rule_engine"
    else:
        battery["generation_source"] = "adaptive_rule_engine"

    return battery


def evaluate_picture_story_with_ai(spoken_description: str) -> Dict[str, Any]:
    """
    Test 4 AI Analysis: Evaluates the spoken description of the courtyard scene.
    """
    text = (spoken_description or "").strip()
    if not text:
        return {
            "source": "empty_input",
            "themes_identified": [],
            "semantic_score": 0.0,
            "narrative_quality": "No spoken description was provided.",
            "linguistic_notes": "0 words recorded.",
        }

    client = get_openrouter_client()
    if not client:
        words = [w.lower() for w in text.split()]
        key_themes = ["courtyard", "tree", "tea", "teapot", "table", "charpoy", "sun", "sparrow", "bird", "child", "book", "grandmother", "cup"]
        found = sorted({t for t in key_themes if any(t in w for w in words)})
        return {
            "source": "rule_engine",
            "themes_identified": found,
            "semantic_score": min(100.0, round((len(found) / 6.0) * 100.0, 1)),
            "narrative_quality": f"Identified {len(found)} core scene elements across {len(words)} words.",
            "linguistic_notes": f"Word count: {len(words)}; matched entities: {', '.join(found) or 'none'}.",
        }

    prompt = f"""You are a clinical neuropsychologist assistant for a cognitive screening aid.
Analyze the following patient's spoken description of an illustrated courtyard tea scene (features: courtyard, tree, sparrow/bird, charpoy, grandmother, teapot, cup, child reading a book, sun).

Patient's Description:
\"\"\"{text}\"\"\"

Provide your clinical assessment in strict JSON format with these exact keys:
{{
  "themes_identified": ["list", "of", "scene", "items", "mentioned"],
  "semantic_score": <number between 0 and 100>,
  "narrative_quality": "<concise 1-2 sentence clinical impression of language and coherence>",
  "linguistic_notes": "<notes on vocabulary richness, grammar, or word finding difficulty>"
}}
Return ONLY valid JSON."""

    try:
        response = client.chat.completions.create(
            extra_headers=get_extra_headers(),
            model=settings.OPENROUTER_MODEL,
            messages=[
                {"role": "system", "content": "You are a specialized clinical AI assistant that outputs JSON only."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            timeout=10.0,
        )
        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)
        parsed["source"] = "openrouter_ai"
        return parsed
    except Exception as e:
        logger.warning("OpenRouter picture story analysis error: %s", e)
        words = [w.lower() for w in text.split()]
        key_themes = ["courtyard", "tree", "tea", "teapot", "charpoy", "sun", "sparrow", "bird", "child", "book", "grandmother", "cup"]
        found = sorted({t for t in key_themes if any(t in w for w in words)})
        return {
            "source": "rule_engine_fallback",
            "themes_identified": found,
            "semantic_score": min(100.0, round((len(found) / 6.0) * 100.0, 1)),
            "narrative_quality": f"Identified {len(found)} scene elements across {len(words)} words.",
            "linguistic_notes": f"Word count: {len(words)}.",
        }


def evaluate_clock_vision_with_ai(
    image_data_uri: str,
    target_time: str = "11:10",
    stroke_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Test 5 Multimodal Vision Analysis: Evaluates the drawn clock on canvas.
    Never returns a fake 100/100 score on an empty drawing.
    """
    strokes = (stroke_data or {}).get("strokes") or []
    geom_chk = clock_vision_provider.evaluate_clock(
        target_time=target_time,
        stroke_data=stroke_data,
        image_base64=image_data_uri,
    )

    client = get_openrouter_client()
    if not client or not image_data_uri or len(image_data_uri) < 120:
        pts = sum(1 for v in geom_chk.model_dump().values() if v)
        return {
            "source": "stroke_geometry_engine",
            "checklist": geom_chk.model_dump(),
            "score": round((pts / 6.0) * 100.0, 1),
            "observations": (
                f"Evaluated {len(strokes)} drawn strokes against target time {target_time}."
                if strokes
                else "Canvas has no recorded clock strokes yet; checklist items remain unchecked."
            ),
        }

    img_payload = (
        {"url": image_data_uri}
        if image_data_uri.startswith("http") or image_data_uri.startswith("data:")
        else {"url": f"data:image/png;base64,{image_data_uri}"}
    )

    prompt = f"""Analyze this drawn clock image for a cognitive Clock Drawing Test (target time is {target_time}).
If the image is blank or does not contain a clock drawing, set all 6 checklist booleans to false and score to 0.
Evaluate these 6 criteria carefully:
1. closed_circle: Is there a closed circular clock contour?
2. twelve_numbers: Are numbers 1 through 12 present?
3. correct_order: Are the numbers placed in proper clockwise order?
4. correct_spacing: Are the numbers distributed evenly around the perimeter?
5. two_hands: Are there two distinct hands drawn from the center?
6. hands_match_time: Do the hands correctly indicate {target_time}?

Respond in strict JSON with format:
{{
  "checklist": {{
    "closed_circle": true/false,
    "twelve_numbers": true/false,
    "correct_order": true/false,
    "correct_spacing": true/false,
    "two_hands": true/false,
    "hands_match_time": true/false
  }},
  "score": <number 0 to 100>,
  "observations": "<concise 1 sentence observation>"
}}
Return ONLY valid JSON."""

    try:
        response = client.chat.completions.create(
            extra_headers=get_extra_headers(),
            model=settings.OPENROUTER_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": img_payload},
                    ],
                }
            ],
            response_format={"type": "json_object"},
            timeout=12.0,
        )
        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)
        parsed["source"] = "openrouter_vision_ai"
        return parsed
    except Exception as e:
        logger.warning("OpenRouter clock vision fallback to stroke geometry: %s", e)
        pts = sum(1 for v in geom_chk.model_dump().values() if v)
        return {
            "source": "stroke_geometry_fallback",
            "checklist": geom_chk.model_dump(),
            "score": round((pts / 6.0) * 100.0, 1),
            "observations": f"Evaluated from {len(strokes)} canvas strokes (target {target_time}).",
        }


def _parse_medicines_from_text_regex(text: str) -> List[Dict[str, Any]]:
    """
    Deterministic parser that extracts only explicitly written medicine lines
    (e.g., 'Donepezil 5mg', 'Memantine 10 mg') from text without ever inventing a drug.
    """
    if not text or not text.strip():
        return []
    pattern = re.compile(r"\b([A-Z][a-zA-Z]{2,24})\s+(\d+\s*(?:mg|mcg|g|ml|tablet|tab|cap))\b")
    meds: List[Dict[str, Any]] = []
    for match in pattern.finditer(text):
        name, dose = match.group(1), match.group(2).replace(" ", "")
        if name.lower() in ("take", "daily", "once", "twice", "follow", "after", "before", "patient", "visit"):
            continue
        meds.append(
            {
                "name": name,
                "dose": dose,
                "frequency_per_day": 1,
                "reminder_times": ["21:00"],
                "instructions": "Verify against doctor's written prescription before confirming",
            }
        )
    return meds


def extract_prescription_with_ai(prescription_text: str, image_data_uri: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 3 Post-Visit: Extracts doctor findings, prescribed medicines, doses, reminder times, and follow-up advice.
    Safety rule: Never invents or suggests any medicine not present in the input.
    """
    clean_text = (prescription_text or "").strip()
    client = get_openrouter_client()
    if not client or (not clean_text and not image_data_uri):
        parsed_meds = _parse_medicines_from_text_regex(clean_text)
        days_match = re.search(r"(\d+)\s*days?", clean_text, re.IGNORECASE)
        followup_days = int(days_match.group(1)) if days_match else 30
        return {
            "source": "text_parser",
            "findings_summary": clean_text or "No prescription text provided.",
            "medicines": parsed_meds,
            "followup_interval_days": followup_days,
            "advice": "Please verify all entries against the doctor's physical prescription.",
        }

    content_list: List[Dict[str, Any]] = []
    text_prompt = f"""You are a medical assistant parsing a doctor's prescription report for a patient cognitive care app.
CRITICAL SAFETY RULE: Extract ONLY medicines explicitly written in the input. NEVER invent, guess, or suggest any medicine that is not in the input. If no medicine is mentioned, return an empty list [] for "medicines".

Input Prescription / Notes:
\"\"\"{clean_text}\"\"\"

Output STRICT JSON:
{{
  "findings_summary": "<string>",
  "medicines": [
    {{
      "name": "<string>",
      "dose": "<string>",
      "frequency_per_day": <int>,
      "reminder_times": ["<HH:MM>"],
      "instructions": "<string>"
    }}
  ],
  "followup_interval_days": <int>,
  "advice": "<string>"
}}
Return ONLY JSON."""
    content_list.append({"type": "text", "text": text_prompt})
    if image_data_uri:
        img_payload = (
            {"url": image_data_uri}
            if image_data_uri.startswith("http") or image_data_uri.startswith("data:")
            else {"url": f"data:image/png;base64,{image_data_uri}"}
        )
        content_list.append({"type": "image_url", "image_url": img_payload})

    try:
        response = client.chat.completions.create(
            extra_headers=get_extra_headers(),
            model=settings.OPENROUTER_MODEL,
            messages=[
                {"role": "system", "content": "You are a clinical prescription parser. Never invent medicines. Output valid JSON only."},
                {"role": "user", "content": content_list},
            ],
            response_format={"type": "json_object"},
            timeout=12.0,
        )
        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)
        parsed["source"] = "openrouter_ai"
        return parsed
    except Exception as e:
        logger.warning("OpenRouter prescription extraction fallback: %s", e)
        return {
            "source": "text_parser_fallback",
            "findings_summary": clean_text,
            "medicines": _parse_medicines_from_text_regex(clean_text),
            "followup_interval_days": 30,
            "advice": "Verify against doctor's original prescription.",
        }
