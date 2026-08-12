"""Jarvis hafıza ve operasyonel bağlam — AI'nin kullanıcıyı gerçekten 'tanıması' için."""
from datetime import date, timedelta

import crud

MEMORY_CATEGORY_LABELS = {
    "preference": "🎯 Tercihler ve alışkanlıklar",
    "note": "📝 Önemli notlar",
    "analysis": "📊 Son koçluk analizleri",
    "physique_analysis": "💪 Fizik gözlemleri",
    "onboarding": "👤 Profil özeti",
    "onboarding_nutrition": "🍽️ Beslenme geçmişi (onboarding)",
    "onboarding_training": "🏋️ Antrenman geçmişi (onboarding)",
    "onboarding_lifestyle": "🌙 Yaşam tarzı (onboarding)",
    "onboarding_voice": "🎙️ Sesli tanışma notları",
    "conversation": "💬 Sohbetten öğrenilenler",
}


def build_memory_block(db) -> str:
    """Kategorize, genişletilmiş hafıza bloğu — AI her mesajda bunu görür."""
    memories = crud.get_recent_memories(db, limit=40)
    if not memories:
        return "\n(Henüz kayıtlı hafıza yok — kullanıcıyı tanımaya başlıyorsun.)\n"

    grouped: dict[str, list[str]] = {}
    for m in memories:
        grouped.setdefault(m.category or "note", []).append(m.content)

    lines = ["\n══════════════════════════════════════",
             "JARVIS KALICI HAFIZASI (her yanıtta bunu dikkate al, çelişme):",
             "══════════════════════════════════════"]
    for category in MEMORY_CATEGORY_LABELS:
        items = grouped.get(category, [])
        if items:
            label = MEMORY_CATEGORY_LABELS[category]
            lines.append(f"\n{label}:")
            for content in items[:5]:
                lines.append(f"  • {content[:400]}")

    for category, items in grouped.items():
        if category not in MEMORY_CATEGORY_LABELS:
            lines.append(f"\n({category}):")
            for content in items[:3]:
                lines.append(f"  • {content[:400]}")

    lines.append("\nHAFIZA KURALI: Kullanıcı geçmişte söylediğini unutma; tercihlerine uygun öneri ver.\n")
    return "\n".join(lines)


def build_operational_context(db, conversation_history: list | None = None) -> str:
    """Bugünkü durum + son konuşma — anlık kararlar için."""
    today = date.today()
    meals_today = crud.get_nutrition_logs_by_date(db, today)
    plan_items = crud.get_meal_plan(db)
    workout_today = crud.get_workout_logs_by_date(db, today)
    week_workouts = crud.get_workout_logs_range(db, days=7)

    lines = [f"\nOPERASYONEL BAĞLAM (bugün: {today.strftime('%d.%m.%Y')}):"]

    if plan_items:
        plan_names = ", ".join(p.meal_name for p in plan_items)
        plan_cal = sum(p.calories or 0 for p in plan_items)
        lines.append(f"- Beslenme planı ({len(plan_items)} öğün): {plan_names} (~{plan_cal:.0f} kcal/gün)")
    else:
        lines.append("- Beslenme planı YOK")

    if meals_today:
        logged_cal = sum(m.calories or 0 for m in meals_today)
        logged_names = ", ".join(m.meal_name for m in meals_today)
        lines.append(f"- Bugün kayıtlı: {logged_names} ({logged_cal:.0f} kcal)")
        if plan_items and len(meals_today) >= len(plan_items):
            lines.append("- NOT: Bugün planın tamamı veya çoğu zaten kayıtlı olabilir.")
    else:
        lines.append("- Bugün henüz öğün kaydı yok")

    if workout_today:
        lines.append(f"- Bugün {len(workout_today)} antrenman seti kayıtlı")
    elif week_workouts:
        lines.append(f"- Son 7 günde {len(week_workouts)} set (bugün antrenman yok)")
    else:
        lines.append("- Son günlerde antrenman kaydı yok")

    if conversation_history:
        recent = conversation_history[-8:]
        if recent:
            lines.append("- Son konuşma:")
            for turn in recent:
                role = "Kullanıcı" if turn.get("role") == "user" else "Jarvis"
                lines.append(f"  {role}: {(turn.get('text') or '')[:180]}")

    lines.append("")
    return "\n".join(lines)


def format_user_prompt(user_message: str, conversation_history: list | None = None) -> str:
    if not conversation_history:
        return user_message
    recent = conversation_history[-6:]
    ctx = []
    for turn in recent:
        if turn.get("role") == "user" and turn.get("text") == user_message:
            continue
        role = "Kullanıcı" if turn.get("role") == "user" else "Jarvis"
        ctx.append(f"{role}: {(turn.get('text') or '')[:300]}")
    if not ctx:
        return user_message
    return "Önceki konuşma:\n" + "\n".join(ctx) + f"\n\nŞimdiki mesaj:\n{user_message}"


def save_conversation_memory(db, user_message: str, assistant_reply: str):
    """Önemli sohbet anlarını hafızaya kaydet (hafif, kural tabanlı)."""
    msg = (user_message or "").lower()
    triggers = [
        ("preference", ["yemem", "sevmem", "alerjim", "intolerans", "vejetaryen", "vegan", "gluten"]),
        ("note", ["sakat", "ağrı", "incitti", "yapamıyorum", "dizim", "belim", "omzum"]),
        ("preference", ["geç yat", "erken kalk", "mesai", "vardiya", "uyku"]),
    ]
    for category, keywords in triggers:
        if any(k in msg for k in keywords):
            crud.create_memory(db, category=category, content=user_message[:500])
            return
