"""Kural tabanlı beslenme planı eşleştirme — AI'den önce çalışır, daha güvenilir."""
import re

import crud


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower().strip()
    tr_map = str.maketrans("ıİğĞüÜşŞöÖçÇ", "iigguussoocc")
    return text.translate(tr_map)


MEAL_ALIASES = {
    "kahvalti": ["kahvaltı", "sabah", "sabah ogunu", "breakfast", "1. ogun", "birinci ogun"],
    "ogle": ["öğle", "öğlen", "ogle yemegi", "öğle yemeği", "lunch", "2. ogun", "ikinci ogun"],
    "aksam": ["akşam", "aksam yemegi", "akşam yemeği", "dinner", "3. ogun", "gece yemegi"],
    "ara": ["ara ogun", "ara öğün", "atistirmalik", "atıştırmalık", "snack", "ikindi", "gece ogunu"],
}

WHOLE_PLAN_RE = re.compile(
    r"(?:"
    r"tum\s+(?:plan(?:im(?:i)?|a)?|menu(?:m(?:u)?)?|beslenme(?:\s+plan(?:im(?:i)?|a)?)?|"
    r"ogun(?:ler(?:im(?:i)?|ini|i)?)?|yemek(?:ler(?:im(?:i)?|ini|i)?)?)|"
    r"butun\s+(?:plan(?:im(?:i)?|a)?|menu(?:m(?:u)?)?|ogun(?:ler(?:im(?:i)?|ini|i)?)?|"
    r"yemek(?:ler(?:im(?:i)?|ini|i)?)?|beslenme)|"
    r"(?:ogun|yemek)lerim(?:i|in|e|in\s+hepsi|in\s+tamami)?|"
    r"(?:ogun|yemek)lerime|"
    r"(?:hepsi|tamami|tumu)\s+(?:ogun|yemek|menu|plan)|"
    r"hepsini\s+(?:yedim|aldim|bitirdim|tamamladim|uyguladim|hallettim)|"
    r"(?:beslenme\s+)?(?:program|plan)(?:im|imi|a)?\s*(?:uygula|uyguladim|takip|yedim|bitirdim|tamamladim|aldim|hallettim)|"
    r"(?:bugunku|gunun|bugunun)\s+(?:beslenme\s+)?(?:program|plan|menu)(?:im|imi|a)?|"
    r"(?:program|plan|menu)(?:a|ima|im)?\s*(?:uygun|gore|dogru)\s*(?:yedim|aldim|uyguladim|tamamladim)|"
    r"onerd(?:igin|iginiz)\s+(?:plan|menu|beslenme)|"
    r"menu(?:yu|yu\s+)?(?:yedim|uyguladim|bitirdim|tamamladim|hallettim)|"
    r"plana?\s+(?:uygun|gore|sadik)\s*(?:yedim|kaldim|uyguladim|tamamladim)|"
    r"(?:\d+|uc|dort|bes|alti)\s+ogun(?:un)?\s+(?:hepsi|tamami|tumu)"
    r")",
    re.IGNORECASE,
)

WHOLE_PLAN_HINT_BLOCKLIST = re.compile(
    r"(?:tum|butun|hepsi|tamami|tumu|ogunler|yemekler|menu|plan(?:im|a)?|program(?:im|a)?|"
    r"beslenme|gunun|bugunku|onerdigin|onerilen)",
    re.IGNORECASE,
)

PLAN_REFERENCE_RE = re.compile(
    r"(?:plan(?:im)?daki|program(?:im)?daki|menu(?:m)?deki|plandan|programdan|onerdigin|onerilen)",
    re.IGNORECASE,
)

LOG_ACTION_RE = re.compile(
    r"(?:yedim|yaptim|uyguladim|takip\s+ettim|bitirdim|tamamladim|hallettim|aldim|tükettim|tukettim|girdim)",
    re.IGNORECASE,
)

COMPLETION_RE = re.compile(
    r"(?:tamamladim|bitirdim|hallettim|uzerinden\s+gectim|son\s+ogunumu\s+da)",
    re.IGNORECASE,
)


def find_plan_meal(plan_items, query: str):
    if not plan_items or not query:
        return None
    q = _normalize_text(query)
    if not q:
        return None

    for item in plan_items:
        if _normalize_text(item.meal_name) == q:
            return item

    for item in plan_items:
        name = _normalize_text(item.meal_name)
        if q in name or name in q:
            return item

    for alias_key, aliases in MEAL_ALIASES.items():
        terms = [_normalize_text(alias_key)] + [_normalize_text(a) for a in aliases]
        if any(term in q for term in terms):
            for item in plan_items:
                name = _normalize_text(item.meal_name)
                if any(term in name for term in terms) or alias_key in name:
                    return item

    from difflib import get_close_matches
    name_map = {_normalize_text(item.meal_name): item for item in plan_items}
    close = get_close_matches(q, list(name_map.keys()), n=1, cutoff=0.55)
    if close:
        return name_map[close[0]]
    return None


def _find_plan_meal_keyword(hint: str) -> bool:
    h = _normalize_text(hint)
    for alias_key, aliases in MEAL_ALIASES.items():
        terms = [_normalize_text(alias_key)] + [_normalize_text(a) for a in aliases]
        if any(term in h for term in terms):
            return True
    return False


def _extract_raw_meal_hint(message: str) -> str | None:
    msg = _normalize_text(message)
    m = re.search(r"plan(?:im)?daki\s+(.+?)(?:\s+yedim|\s+aldim|\s+uyguladim|\s+tamamladim|$)", msg)
    if m:
        return m.group(1).strip()
    m = re.search(r"program(?:im)?daki\s+(.+?)(?:\s+yedim|\s+aldim|\s+uyguladim|\s+tamamladim|$)", msg)
    if m:
        return m.group(1).strip()
    for alias_key, aliases in MEAL_ALIASES.items():
        terms = [_normalize_text(alias_key)] + [_normalize_text(a) for a in aliases]
        if any(term in msg for term in terms):
            return alias_key
    return None


def _is_whole_plan_hint(hint: str) -> bool:
    if not hint:
        return False
    h = _normalize_text(hint)
    if WHOLE_PLAN_RE.search(h):
        return True
    if WHOLE_PLAN_HINT_BLOCKLIST.search(h) and not _find_plan_meal_keyword(h):
        return True
    return False


def wants_whole_plan_log(message: str) -> bool:
    msg = _normalize_text(message)
    if WHOLE_PLAN_RE.search(msg):
        return True
    if COMPLETION_RE.search(msg) and re.search(r"(?:ogun|yemek|plan|menu|beslenme|program)", msg):
        return True
    if LOG_ACTION_RE.search(msg) and re.search(
        r"(?:tum|butun|hepsi|tamami|tumu)\s*(?:ogun|yemek)|"
        r"(?:ogun|yemek)lerim(?:i|in|e)?|(?:ogun|yemek)lerime|"
        r"hepsini\s+(?:ogun|yemek|menu)",
        msg,
    ):
        return True
    if LOG_ACTION_RE.search(msg) and re.search(r"(?:beslenme\s+)?(?:program|plan|menu)", msg):
        hint = _extract_raw_meal_hint(message)
        if not hint or _is_whole_plan_hint(hint):
            return True
    return False


def extract_meal_hint(message: str) -> str | None:
    if wants_whole_plan_log(message):
        return None
    hint = _extract_raw_meal_hint(message)
    if hint and _is_whole_plan_hint(hint):
        return None
    return hint


def wants_plan_meal_log(message: str) -> bool:
    if wants_whole_plan_log(message):
        return False
    msg = _normalize_text(message)
    if PLAN_REFERENCE_RE.search(msg):
        return True
    if extract_meal_hint(message) and LOG_ACTION_RE.search(msg):
        return True
    if re.search(r"(?:kahvalti|ogle|aksam|ara\s+ogun|atistirmalik).*(?:yedim|aldim|uyguladim|tamamladim)", msg):
        return True
    return False


def clean_user_message(message: str) -> str:
    if not message:
        return ""
    cleaned = message.strip()
    cleaned = re.sub(r"^[\"'«»]+|[\"'«»!?.,;:]+$", "", cleaned).strip()
    return cleaned or message.strip()


def log_plan_meal(db, plan_item) -> dict:
    import schemas
    crud.create_nutrition_log(db, schemas.NutritionLogCreate(
        meal_name=plan_item.meal_name,
        ingredients=plan_item.description,
        calories=plan_item.calories,
        protein=plan_item.protein,
        carbs=plan_item.carbs,
        fats=plan_item.fats,
    ))
    return {
        "intent": "log_food",
        "jarvis_reply": (
            f"✅ {plan_item.meal_name} kaydedildi efendim ({plan_item.calories:.0f} kcal, "
            f"{plan_item.protein:.0f}g protein) — plandaki haliyle."
        ),
        "_food_reply_is_final": True,
    }


def log_all_plan_meals(db, plan_items) -> dict:
    import schemas
    total_cal, total_prot = 0.0, 0.0
    names = []
    for item in plan_items:
        crud.create_nutrition_log(db, schemas.NutritionLogCreate(
            meal_name=item.meal_name,
            ingredients=item.description,
            calories=item.calories,
            protein=item.protein,
            carbs=item.carbs,
            fats=item.fats,
        ))
        total_cal += item.calories or 0
        total_prot += item.protein or 0
        names.append(item.meal_name)
    return {
        "intent": "log_food",
        "jarvis_reply": (
            f"✅ Bugünkü beslenme planının tamamını kaydettim efendim: {', '.join(names)}.\n"
            f"Toplam: {total_cal:.0f} kcal, {total_prot:.0f}g protein. Helal olsun efendim!"
        ),
        "_food_reply_is_final": True,
    }


def no_plan_reply() -> dict:
    return {
        "intent": "chat",
        "jarvis_reply": (
            "Kayıtlı bir beslenme planın yok efendim. Önce /beslenme yazıp planı oluştur "
            "ve ✅ Onayla; sonra 'tüm öğünlerimi tamamladım' veya 'planımdaki kahvaltıyı yedim' diyebilirsin."
        ),
        "_food_reply_is_final": True,
    }


def try_resolve_plan_food_locally(user_message: str, db) -> dict | None:
    plan_items = crud.get_meal_plan(db)
    msg_norm = _normalize_text(user_message)

    refers_to_plan = (
        wants_whole_plan_log(user_message)
        or wants_plan_meal_log(user_message)
        or PLAN_REFERENCE_RE.search(msg_norm)
    )

    if not plan_items:
        if refers_to_plan:
            return no_plan_reply()
        return None

    if wants_whole_plan_log(user_message):
        return log_all_plan_meals(db, plan_items)

    if wants_plan_meal_log(user_message):
        hint = extract_meal_hint(user_message)
        if hint:
            matched = find_plan_meal(plan_items, hint)
            if matched:
                return log_plan_meal(db, matched)
        if PLAN_REFERENCE_RE.search(msg_norm) and LOG_ACTION_RE.search(msg_norm):
            names = ", ".join(p.meal_name for p in plan_items)
            return {
                "intent": "chat",
                "jarvis_reply": (
                    f"Planında şu öğünler var efendim: {names}.\n"
                    f"Hangi öğünü yedin? Veya hepsini yediysen 'tüm öğünlerimi tamamladım' diyebilirsin."
                ),
                "_food_reply_is_final": True,
            }
    return None


def validate_food_intent(user_message: str, data: dict, plan_items) -> dict:
    data = dict(data or {})
    if wants_whole_plan_log(user_message):
        data["log_entire_plan"] = True
        data["matched_plan_meal"] = None
        return data
    matched_name = data.get("matched_plan_meal")
    if matched_name and _is_whole_plan_hint(str(matched_name)):
        data["log_entire_plan"] = True
        data["matched_plan_meal"] = None
        return data
    if matched_name and plan_items and not find_plan_meal(plan_items, matched_name):
        hint = extract_meal_hint(user_message)
        if hint:
            corrected = find_plan_meal(plan_items, hint)
            if corrected:
                data["matched_plan_meal"] = corrected.meal_name
    if not data.get("log_entire_plan") and not data.get("matched_plan_meal"):
        hint = extract_meal_hint(user_message)
        if hint and plan_items:
            matched = find_plan_meal(plan_items, hint)
            if matched:
                data["matched_plan_meal"] = matched.meal_name
    return data
