import hashlib
import json
import logging
from pathlib import Path
import random
import re
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from urllib.request import Request, urlopen
from fastapi import HTTPException, status
from openai import OpenAI
from backend.app.core.config import settings

logger = logging.getLogger("yaadasht.ai")
SCENE_IMAGES_DIR = Path(__file__).resolve().parents[3] / "uploads" / "scene_images"
SCENE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def _generate_and_save_scene_image(image_prompt: str, seed: int) -> str:
    """
    Generates a real AI illustration image from the AI-written scene prompt and saves it locally.
    """
    clean_prompt = (image_prompt or "warm realistic illustration of everyday family life").strip()
    url = (
        f"https://image.pollinations.ai/prompt/{quote(clean_prompt)}"
        f"?width=640&height=360&nologo=true&seed={abs(int(seed)) % 999999}"
    )
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=25) as resp:
        img_bytes = resp.read()
    if not img_bytes or len(img_bytes) < 1000:
        raise ValueError("Generated scene image was empty.")
    filename = f"scene_{uuid.uuid4().hex[:12]}.jpg"
    (SCENE_IMAGES_DIR / filename).write_bytes(img_bytes)
    return f"/scene-images/{filename}"


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


def get_openrouter_client() -> OpenAI:
    api_key = settings.OPENROUTER_API_KEY.strip()
    if not api_key or api_key == "your_openrouter_api_key_here":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenRouter API key is not configured.",
        )
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
    previous_categories: Optional[List[str]] = None,
    previous_scenes: Optional[List[str]] = None,
    previous_clock_times: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Generates a 100% live AI-personalized 7-test cognitive battery via OpenRouter AI
    based on the patient's intake profile (age, education, occupation, city, observed symptoms,
    medical conditions), with no hardcoded fallback pools.
    """
    prev_set = {w.strip().lower() for w in previous_words if w}
    prev_cats = [c.strip() for c in (previous_categories or []) if c and c.strip()]
    prev_scenes = [s.strip() for s in (previous_scenes or []) if s and s.strip()]
    prev_clocks = [t.strip() for t in (previous_clock_times or []) if t and t.strip()]
    profile_hash = int(
        hashlib.sha256(
            f"{person.get('id','')}-{person.get('name','')}-{person.get('age',65)}-{person.get('education_level','')}-{person.get('occupation','')}-{session_index}".encode("utf-8")
        ).hexdigest()[:8],
        16,
    )
    dot_coords = generate_randomized_dot_coords(f"{person.get('id','')}-{session_index}-{profile_hash}")

    symptoms_str = ", ".join(person.get("observed_symptoms") or []) or "general memory screening"
    conditions_str = ", ".join(person.get("medical_conditions") or []) or "none reported"

    client = get_openrouter_client()
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
- Previously Used Fluency Categories (DO NOT REPEAT ANY OF THESE): {prev_cats}
- Previously Used Picture Scenes (DO NOT REPEAT ANY OF THESE): {prev_scenes}
- Previously Used Clock Target Times (DO NOT REPEAT ANY OF THESE): {prev_clocks}

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
  "fluency_category": "<fresh category name NOT in previously used categories, e.g. Fruits & Vegetables, Kitchen & Cooking Items, Farming & Garden Tools, Vehicles & Transport, Clothing & Accessories, or Household Furniture>",
  "fluency_prompt": "<clear 1-sentence spoken instruction for the 60-second verbal fluency challenge for that exact category>",
  "fluency_valid_items": ["35 common English nouns belonging to the chosen fluency_category"],
  "picture_scene_title": "<unique everyday scene title tailored to {person.get('city')} / {person.get('occupation', 'daily life')}, NOT in previously used scenes, e.g. Morning Village Market, Family Breakfast Table, Farmer's Harvest Field, Sunny Park Walk, or Rainy Veranda Afternoon>",
  "picture_story_prompt": "<1-sentence tailored prompt asking {person.get('name')} to describe this specific scene in detail>",
  "picture_target_items": ["15 key English nouns/verbs visible in your chosen scene"],
  "picture_image_prompt": "<rich, detailed visual prompt for an AI image generator describing a warm, realistic illustration of this exact scene with clear people, objects, and actions, no text in the image>",
  "test5_instruction": "<1-sentence tailored instruction for delayed recall of the 5 words without looking back>",
  "clinical_rationale": "<1-2 sentence explanation of how this session is tailored to {person.get('name')}'s profile and symptoms>"
}}
Return ONLY valid JSON without markdown explanation."""

    try:
        response = client.chat.completions.create(
            extra_headers=get_extra_headers(),
            model=settings.OPENROUTER_MODEL,
            temperature=0.85,
            messages=[
                {"role": "system", "content": "You output strict clinical JSON only. Vary your question phrasing naturally for every patient."},
                {"role": "user", "content": prompt},
            ],
            timeout=25.0,
        )
        content = response.choices[0].message.content or "{}"
        ai_data = _extract_json_dict(content)
        if not ai_data:
            raise ValueError("AI returned an empty or invalid JSON response.")
    except Exception as exc:
        logger.error("OpenRouter AI test generation error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to generate AI test right now. Please check your internet connection and try again.",
        )

    ai_words = [str(w).strip().lower() for w in (ai_data.get("words_en") or []) if str(w).strip()]
    fluency_items = [str(x).strip().lower() for x in (ai_data.get("fluency_valid_items") or []) if str(x).strip()]
    picture_items = [str(x).strip().lower() for x in (ai_data.get("picture_target_items") or []) if str(x).strip()]
    image_prompt = str(ai_data.get("picture_image_prompt") or ai_data.get("picture_scene_title") or "")
    try:
        picture_image_url = _generate_and_save_scene_image(image_prompt, profile_hash + session_index)
    except Exception as img_exc:
        logger.warning("Scene image generation notice: %s", img_exc)
        picture_image_url = ""

    return {
        "generation_mode": "personalized_baseline",
        "generation_source": "openrouter_ai",
        "patient_context": {
            "age": person.get("age"),
            "education_level": person.get("education_level", "secondary"),
            "occupation": person.get("occupation", "retired"),
            "city": person.get("city", "Lahore"),
            "observed_symptoms": person.get("observed_symptoms", []),
            "medical_conditions": person.get("medical_conditions", []),
        },
        "orientation_questions": ai_data.get("orientation_questions") or {},
        "words_en": ai_words,
        "words_ur": ai_words,
        "words_roman_ur": ai_words,
        "fluency_category": str(ai_data.get("fluency_category") or ""),
        "fluency_prompt": str(ai_data.get("fluency_prompt") or ""),
        "fluency_valid_items": fluency_items,
        "picture_scene": str(ai_data.get("picture_scene_title") or "ai_scene").lower().replace(" ", "_"),
        "picture_scene_title": str(ai_data.get("picture_scene_title") or ""),
        "picture_story_prompt": str(ai_data.get("picture_story_prompt") or ""),
        "picture_target_items": picture_items,
        "picture_image_url": picture_image_url,
        "test5_instruction": str(ai_data.get("test5_instruction") or ai_data.get("test7_instruction") or ""),
        "clinical_rationale": str(ai_data.get("clinical_rationale") or ""),
    }


def generate_post_visit_adaptive_test(
    person: Dict[str, Any],
    last_session: Optional[Dict[str, Any]],
    last_results: List[Dict[str, Any]],
    doctor_doc: Optional[Dict[str, Any]],
    medicines: List[Dict[str, Any]],
    previous_words: List[str],
    session_index: int = 1,
    use_ai_online: bool = True,
    previous_categories: Optional[List[str]] = None,
    previous_scenes: Optional[List[str]] = None,
    previous_clock_times: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Stage 3 Post-Visit Adaptive Test Generator (100% Live OpenRouter AI, no fallback):
    Builds a targeted follow-up test based on:
    1. The patient's last test scores, domain weaknesses, and missed markers
    2. The doctor's post-visit findings and watch_domains
    3. Confirmed medicines currently being taken
    """
    prev_set = {w.strip().lower() for w in previous_words if w}
    prev_cats = [c.strip() for c in (previous_categories or []) if c and c.strip()]
    prev_scenes = [s.strip() for s in (previous_scenes or []) if s and s.strip()]
    prev_clocks = [t.strip() for t in (previous_clock_times or []) if t and t.strip()]

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
    active_meds = [f"{m['name']} ({m['dose']})" for m in medicines if m.get("active", True)]
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

    client = get_openrouter_client()
    prompt = f"""You are a clinical neuropsychologist generating a POST-VISIT ADAPTIVE FOLLOW-UP cognitive test for an Alzheimer's / memory care patient.
Patient Info: {person.get('name')}, {person.get('age')}yo {person.get('gender')} in {person.get('city')}, education: {person.get('education_level', 'secondary')}.
Previous Session Total Score: {last_total}
Previous Domain Scores: {json.dumps(last_domains)}
Weak / Watch Domains to Probe: {watch_domains}
Previous Errors / Missed Markers: {missed_markers[:10]}
Doctor's Post-Visit Findings: {doc_findings or 'Follow-up evaluation'}
Active Confirmed Medicines: {active_meds}
Words Already Used in Previous Sessions (NEVER REPEAT): {list(prev_set)}
Fluency Categories Already Used (NEVER REPEAT): {prev_cats}
Picture Scenes Already Used (NEVER REPEAT): {prev_scenes}
Clock Target Times Already Used (NEVER REPEAT): {prev_clocks}

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
  "fluency_category": "<fresh category name NOT in previously used categories>",
  "fluency_prompt": "<1-sentence spoken instruction for 60s fluency for that exact category>",
  "fluency_valid_items": ["35 common English nouns belonging to the chosen fluency_category"],
  "picture_scene_title": "<brand-new everyday scene title NOT in previously used scenes>",
  "picture_story_prompt": "<1-sentence prompt asking to describe this specific scene with focus on actions and objects>",
  "picture_target_items": ["15 key English nouns/verbs visible in your chosen scene"],
  "picture_image_prompt": "<rich, detailed visual prompt for an AI image generator describing a warm, realistic illustration of this exact scene with clear people, objects, and actions, no text in the image>",
  "test5_instruction": "<1-sentence instruction for delayed recall of the 5 words>",
  "clinical_rationale": "<2-sentence clinical explanation of how this follow-up test adapts to the last test's weak domains and doctor's findings>"
}}
Return ONLY valid JSON without markdown explanation."""

    try:
        response = client.chat.completions.create(
            extra_headers=get_extra_headers(),
            model=settings.OPENROUTER_MODEL,
            temperature=0.85,
            messages=[
                {"role": "system", "content": "You output strict clinical JSON only. Vary your question phrasing naturally for every patient."},
                {"role": "user", "content": prompt},
            ],
            timeout=25.0,
        )
        content = response.choices[0].message.content or "{}"
        ai_data = _extract_json_dict(content)
        if not ai_data:
            raise ValueError("AI returned an empty or invalid JSON response.")
    except Exception as exc:
        logger.error("OpenRouter adaptive test generation error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to generate adaptive AI test right now. Please check your internet connection and try again.",
        )

    ai_words = [str(w).strip().lower() for w in (ai_data.get("words_en") or []) if str(w).strip()]
    fluency_items = [str(x).strip().lower() for x in (ai_data.get("fluency_valid_items") or []) if str(x).strip()]
    picture_items = [str(x).strip().lower() for x in (ai_data.get("picture_target_items") or []) if str(x).strip()]
    image_prompt = str(ai_data.get("picture_image_prompt") or ai_data.get("picture_scene_title") or "")
    try:
        picture_image_url = _generate_and_save_scene_image(image_prompt, session_index + 777)
    except Exception as img_exc:
        logger.warning("Adaptive scene image generation notice: %s", img_exc)
        picture_image_url = ""

    return {
        "generation_mode": "post_visit_adaptive",
        "generation_source": "openrouter_ai",
        "adaptive_context": adaptive_context,
        "orientation_questions": ai_data.get("orientation_questions") or {},
        "words_en": ai_words,
        "words_ur": ai_words,
        "words_roman_ur": ai_words,
        "fluency_category": str(ai_data.get("fluency_category") or ""),
        "fluency_prompt": str(ai_data.get("fluency_prompt") or ""),
        "fluency_valid_items": fluency_items,
        "picture_scene": str(ai_data.get("picture_scene_title") or "ai_scene").lower().replace(" ", "_"),
        "picture_scene_title": str(ai_data.get("picture_scene_title") or ""),
        "picture_story_prompt": str(ai_data.get("picture_story_prompt") or ""),
        "picture_target_items": picture_items,
        "picture_image_url": picture_image_url,
        "test5_instruction": str(ai_data.get("test5_instruction") or ai_data.get("test7_instruction") or ""),
        "clinical_rationale": str(ai_data.get("clinical_rationale") or ""),
    }


def evaluate_picture_story_with_ai(
    spoken_description: str,
    scene_title: str = "",
    target_items: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Test 4 AI Analysis: Evaluates the spoken description of the AI-generated scene via OpenRouter AI.
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

    scene_label = scene_title.strip() or "the illustrated scene"
    items_hint = ", ".join(target_items or []) or "people, objects, background, actions"
    client = get_openrouter_client()
    prompt = f"""You are a clinical neuropsychologist assistant for a cognitive screening aid.
Analyze the following patient's spoken description of an illustrated scene titled "{scene_label}" (key elements: {items_hint}).

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
            timeout=15.0,
        )
        content = response.choices[0].message.content or "{}"
        parsed = _extract_json_dict(content)
        parsed["source"] = "openrouter_ai"
        return parsed
    except Exception as exc:
        logger.error("OpenRouter picture story analysis error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to analyze picture story with AI right now. Please try again.",
        )


def evaluate_clock_vision_with_ai(
    image_data_uri: str,
    target_time: str = "11:10",
    stroke_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Test 5 Multimodal Vision Analysis: Evaluates the drawn clock on canvas via OpenRouter Vision AI.
    """
    if not image_data_uri or len(image_data_uri) < 120:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please draw the clock on the canvas first.",
        )

    client = get_openrouter_client()
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
            timeout=20.0,
        )
        content = response.choices[0].message.content or "{}"
        parsed = _extract_json_dict(content)
        parsed["source"] = "openrouter_vision_ai"
        return parsed
    except Exception as exc:
        logger.error("OpenRouter clock vision error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to analyze clock drawing with Vision AI right now. Please try again.",
        )


def extract_prescription_with_ai(prescription_text: str, image_data_uri: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 3 Post-Visit: Extracts doctor findings, prescribed medicines, doses, reminder times, and follow-up advice via OpenRouter AI.
    Safety rule: Never invents or suggests any medicine not present in the input.
    """
    clean_text = (prescription_text or "").strip()
    if not clean_text and not image_data_uri:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide doctor findings text or a prescription image.",
        )

    client = get_openrouter_client()
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
            timeout=20.0,
        )
        content = response.choices[0].message.content or "{}"
        parsed = _extract_json_dict(content)
        parsed["source"] = "openrouter_ai"
        return parsed
    except Exception as exc:
        logger.error("OpenRouter prescription extraction error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to extract prescription with AI right now. Please try again.",
        )
