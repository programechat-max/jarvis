import os
import logging
import datetime as dt

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date

import models, schemas, crud, ai_core, progression
import jarvis_brain
from database import SessionLocal, engine, get_db, migrate_schema

logger = logging.getLogger(__name__)

migrate_schema()

app = FastAPI(title="Jarvis Core Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================
# SİSTEM DURUMU
# ==========================================
@app.get("/api/status")
def get_status(db: Session = Depends(get_db)):
    """Frontend'in kilit ekranını açıp açmayacağına karar vermesi için kullanılır.
    Profil onboarding tamamlandıysa VEYA en az bir kayıt varsa kurulum tamamlanmış sayılır."""
    profile = crud.get_or_create_profile(db)
    has_any_log = (
        db.query(models.NutritionLog).first() is not None
        or db.query(models.WorkoutLog).first() is not None
    )
    return {"is_setup_complete": bool(profile.onboarding_completed or has_any_log)}


# ==========================================
# PROFİL
# ==========================================
@app.get("/api/profile", response_model=schemas.UserProfileResponse)
def get_profile(db: Session = Depends(get_db)):
    return crud.get_or_create_profile(db)


@app.put("/api/profile", response_model=schemas.UserProfileResponse)
def update_profile(data: schemas.UserProfileBase, db: Session = Depends(get_db)):
    return crud.update_profile(db, data.model_dump(exclude_unset=True))


# ==========================================
# ONBOARDING (vücut videosu + sesli anlatım ile profil oluşturma)
# ==========================================
MAX_UPLOAD_BYTES = 300 * 1024 * 1024  # 300MB - bunun üstü tarayıcıda zaten "Load failed"a yol açar


@app.post("/api/onboarding/video")
async def onboarding_analyze_video(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Onboarding sırasında iyi ışıkta çekilen VÜCUT VİDEOSUNU analiz eder.
    Aynı Gemini vision motorunu (analyze_physique_media) kullanır: fizik/simetri
    değerlendirmesi yapar, kalıcı hafızaya (UserMemory) özet yazar, varsa somut
    antrenman/beslenme talimatı çıkarır - bunlar sonraki program üretiminde kullanılır."""
    video_bytes = await file.read()
    if not video_bytes:
        raise HTTPException(status_code=400, detail="Boş video dosyası.")
    if len(video_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Video çok büyük (300MB üstü). Kaydı 10-15 saniyeye indirip tekrar dener misin?")
    mime_type = file.content_type or "video/webm"
    logger.info(f"[ONBOARDING] Video alındı: {len(video_bytes) / (1024*1024):.1f}MB, mime={mime_type}")

    try:
        os.makedirs("user_videos", exist_ok=True)
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = ".webm" if "webm" in mime_type else ".mp4"
        with open(os.path.join("user_videos", f"onboarding_{ts}{ext}"), "wb") as f:
            f.write(video_bytes)
    except Exception as e:
        logger.warning(f"Onboarding videosu diske yazılamadı: {e}")

    try:
        return ai_core.analyze_physique_media(video_bytes, mime_type, db)
    except Exception as e:
        # analyze_physique_media zaten kendi içinde hataları yakalayıp güvenli bir dict
        # döndürüyor; buraya bir şey sızarsa bile bağlantıyı koparmak yerine düzgün bir
        # JSON hata dönelim ki tarayıcıda anlamsız "Load failed" yerine gerçek mesaj görünsün.
        logger.error(f"[ONBOARDING] Video endpoint beklenmeyen hata: {e}")
        raise HTTPException(status_code=500, detail=f"Video işlenirken sunucu hatası: {e}")


@app.post("/api/onboarding/voice")
async def onboarding_analyze_voice(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Onboarding sırasında kaydedilen SESLİ ANLATIMI (güncel beslenme, antrenman,
    günlük rutin, gerçek hedef) önce metne çevirir (transcribe_audio), sonra bu metni
    yapılandırılmış profil alanlarına ve kalıcı hafızaya dönüştürür
    (extract_profile_from_transcript)."""
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Boş ses dosyası.")
    if len(audio_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Ses kaydı çok büyük. Daha kısa bir kayıt dener misin?")
    mime_type = file.content_type or "audio/webm"
    logger.info(f"[ONBOARDING] Ses alındı: {len(audio_bytes) / (1024*1024):.1f}MB, mime={mime_type}")

    try:
        os.makedirs("user_audio", exist_ok=True)
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = ".webm" if "webm" in mime_type else ".ogg"
        with open(os.path.join("user_audio", f"onboarding_{ts}{ext}"), "wb") as f:
            f.write(audio_bytes)
    except Exception as e:
        logger.warning(f"Onboarding ses kaydı diske yazılamadı: {e}")

    try:
        transcript = ai_core.transcribe_audio(audio_bytes, mime_type)
        return ai_core.extract_profile_from_transcript(transcript, db)
    except Exception as e:
        logger.error(f"[ONBOARDING] Ses endpoint beklenmeyen hata: {e}")
        raise HTTPException(status_code=500, detail=f"Ses işlenirken sunucu hatası: {e}")


@app.post("/api/onboarding/complete")
def onboarding_complete(data: schemas.UserProfileBase, db: Session = Depends(get_db)):
    """Onboarding'in son adımı. Formdaki temel bilgileri (yaş/boy/kilo/hedef/deneyim vb.)
    profile yazar ve kurulumu tamamlanmış işaretler. Video/ses analizinden biriken
    UserMemory kayıtları + zenginleşmiş profil, build_system_prompt üzerinden otomatik
    olarak devreye girer - bu yüzden burada ekstra talimat geçmeye gerek yok, AI zaten
    kullanıcıyı 'tanıyarak' antrenman programını ve beslenme planını üretir."""
    if not (data.name and data.name.strip()):
        raise HTTPException(status_code=400, detail="İsim alanı zorunludur.")
    updates = data.model_dump(exclude_unset=True)
    updates["onboarding_completed"] = True
    profile = crud.get_or_create_profile(db)
    if not profile.started_at:
        updates["started_at"] = dt.datetime.utcnow()
    profile = crud.update_profile(db, updates)

    # generate_workout_program zaten düz pydantic objeleri döner (bkz. fonksiyon içi not);
    # generate_meal_plan ise ORM nesneleri döner - jsonable_encoder'ın SQLAlchemy iç
    # durumuna (_sa_instance_state) takılmaması için burada açıkça pydantic'e çeviriyoruz.
    workout_programs = ai_core.generate_workout_program(db)
    meal_plan_orm = ai_core.generate_meal_plan(db)
    meal_plan = [schemas.MealPlanItemResponse.model_validate(item) for item in meal_plan_orm]

    return {
        "profile": schemas.UserProfileResponse.model_validate(profile),
        "workout_programs": workout_programs,
        "meal_plan": meal_plan,
    }


# ==========================================
# BESLENME (frontend /api/nutrition -> bugünün öğün listesi bekliyor)
# ==========================================
@app.get("/api/nutrition")
def get_nutrition_today_list(db: Session = Depends(get_db)):
    """Frontend'in beklediği düz liste: [{calories, protein, carbs, ...}, ...]"""
    logs = crud.get_nutrition_logs_by_date(db, date.today())
    return [
        {
            "id": l.id,
            "meal_name": l.meal_name,
            "ingredients": l.ingredients,
            "calories": l.calories,
            "target_protein": l.protein,
            "target_carbs": l.carbs,
            "target_fat": l.fats,
            "time_target": l.time_target,
        }
        for l in logs
    ]


@app.get("/api/nutrition/today")
def get_today_nutrition(db: Session = Depends(get_db)):
    logs = crud.get_nutrition_logs_by_date(db, date.today())
    total_cals = sum(l.calories or 0 for l in logs)
    total_protein = sum(l.protein or 0 for l in logs)
    total_carbs = sum(l.carbs or 0 for l in logs)
    total_fats = sum(l.fats or 0 for l in logs)
    return {
        "date": str(date.today()),
        "summary": {"calories": total_cals, "protein": total_protein, "carbs": total_carbs, "fats": total_fats},
        "meals": logs,
    }


@app.get("/api/nutrition/history")
def get_nutrition_history(days: int = 7, db: Session = Depends(get_db)):
    return crud.get_nutrition_history(db, days=days)


@app.get("/api/nutrition/day")
def get_nutrition_for_day(day: str, db: Session = Depends(get_db)):
    """Belirli bir güne ait beslenme penceresi. 'day' formatı: YYYY-MM-DD."""
    try:
        target_date = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz tarih formatı, YYYY-MM-DD kullan.")

    logs = crud.get_nutrition_logs_by_date(db, target_date)
    total_cals = sum(l.calories or 0 for l in logs)
    total_protein = sum(l.protein or 0 for l in logs)
    total_carbs = sum(l.carbs or 0 for l in logs)
    total_fats = sum(l.fats or 0 for l in logs)
    return {
        "date": day,
        "summary": {"calories": total_cals, "protein": total_protein, "carbs": total_carbs, "fats": total_fats},
        "meals": logs,
    }


@app.post("/api/nutrition", response_model=schemas.NutritionLogResponse)
def create_nutrition_entry(entry: schemas.NutritionLogCreate, db: Session = Depends(get_db)):
    return crud.create_nutrition_log(db, entry)


MAX_PHOTO_BYTES = 15 * 1024 * 1024


@app.post("/api/nutrition/photo")
async def analyze_nutrition_photo(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Yemek/fizik fotoğrafını analiz eder ama kaydetmez — web arayüzünde kullanıcı
    makroları onayladıktan sonra /api/nutrition/photo/confirm ile kaydedilir."""
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Boş fotoğraf dosyası.")
    if len(image_bytes) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Fotoğraf çok büyük (15MB üstü).")
    mime_type = file.content_type or "image/jpeg"
    try:
        return ai_core.analyze_photo(image_bytes, mime_type, db, save=False)
    except Exception as e:
        logger.error(f"[NUTRITION] Fotoğraf analizi hatası: {e}")
        raise HTTPException(status_code=500, detail=f"Fotoğraf analiz edilemedi: {e}")


@app.post("/api/nutrition/photo/confirm", response_model=schemas.NutritionLogResponse)
def confirm_nutrition_photo(entry: schemas.NutritionLogCreate, db: Session = Depends(get_db)):
    """Web'de fotoğraf analizi sonrası kullanıcının onayladığı öğünü kaydeder."""
    return crud.create_nutrition_log(db, entry)


# ==========================================
# JARVIS SOHBET (web arayüzü)
# ==========================================
@app.post("/api/chat", response_model=schemas.ChatResponse)
def chat_with_jarvis(body: schemas.ChatRequest, db: Session = Depends(get_db)):
    """Web dashboard'dan Jarvis ile sohbet — jarvis_brain zeka katmanı ile güçlendirilmiş."""
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Mesaj boş olamaz.")
    session_id = body.session_id or "default"
    result = ai_core.process_message(message, db, session_id=session_id)
    return schemas.ChatResponse(
        intent=result.get("intent", "chat"),
        jarvis_reply=result.get("jarvis_reply", "Anlayamadım efendim, tekrar dener misiniz?"),
        data=result.get("data") or {},
        enriched=bool(result.get("_enriched")),
        training_advice=result.get("data", {}).get("training_advice"),
    )


@app.get("/api/chat/history")
def get_chat_history(session_id: str = "default", limit: int = 40, db: Session = Depends(get_db)):
    rows = crud.get_chat_history(db, session_id=session_id, limit=limit)
    return [
        {"role": r.role, "text": r.content, "intent": r.intent, "created_at": r.created_at.isoformat()}
        for r in rows
    ]


@app.delete("/api/chat/history")
def clear_chat_history(session_id: str = "default", db: Session = Depends(get_db)):
    deleted = crud.clear_chat_history(db, session_id=session_id)
    return {"deleted": deleted}


MAX_CHAT_PHOTO_BYTES = 15 * 1024 * 1024
MAX_CHAT_MEDIA_BYTES = 300 * 1024 * 1024


def _chat_response_from_result(result: dict, media_type: str = None, transcript: str = None) -> schemas.ChatResponse:
    return schemas.ChatResponse(
        intent=result.get("intent", "chat"),
        jarvis_reply=result.get("jarvis_reply", "Anlayamadım efendim, tekrar dener misiniz?"),
        data=result.get("data") or {},
        enriched=bool(result.get("_enriched")),
        training_advice=result.get("data", {}).get("training_advice"),
        media_type=media_type,
        transcript=transcript,
    )


@app.post("/api/chat/voice", response_model=schemas.ChatResponse)
async def chat_voice(
    file: UploadFile = File(...),
    session_id: str = "default",
    db: Session = Depends(get_db),
):
    """Jarvis sohbetine ses kaydı gönder — transkribe edilip normal chat akışından işlenir."""
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Boş ses dosyası.")
    if len(audio_bytes) > MAX_CHAT_MEDIA_BYTES:
        raise HTTPException(status_code=413, detail="Ses kaydı çok büyük. Daha kısa bir kayıt dener misin?")
    mime_type = file.content_type or "audio/webm"
    transcript = ai_core.transcribe_audio(audio_bytes, mime_type)
    if not transcript or transcript == "[ANLAŞILAMADI]":
        raise HTTPException(status_code=400, detail="Ses kaydı anlaşılamadı. Daha net konuşup tekrar dener misin?")
    result = ai_core.process_message(transcript, db, session_id=session_id)
    return _chat_response_from_result(result, media_type="voice", transcript=transcript)


@app.post("/api/chat/photo", response_model=schemas.ChatResponse)
async def chat_photo(
    file: UploadFile = File(...),
    session_id: str = "default",
    db: Session = Depends(get_db),
):
    """Jarvis sohbetine fotoğraf gönder — yemek veya fizik analizi yapılır."""
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Boş fotoğraf dosyası.")
    if len(image_bytes) > MAX_CHAT_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Fotoğraf çok büyük (15MB üstü).")
    mime_type = file.content_type or "image/jpeg"
    crud.save_chat_message(db, "user", "📷 Fotoğraf gönderildi", session_id=session_id)

    analysis = ai_core.analyze_photo(image_bytes, mime_type, db, save=True)
    photo_type = analysis.get("photo_type")

    if photo_type == "food" and analysis.get("food"):
        food = analysis["food"]
        jarvis_reply = (
            f"✅ Fotoğraftan yemeği tanıdım efendim: {food.get('meal_name', 'Öğün')} — "
            f"{food.get('calories', 0):.0f} kcal, {food.get('protein', 0):.0f}g protein. Kaydettim."
        )
        if food.get("confidence") == "low":
            jarvis_reply += " (Makrolar tahmini — emin değilsen düzeltebilirsin.)"
        intent = "log_food"
    elif photo_type == "physique" and analysis.get("physique"):
        jarvis_reply = analysis["physique"].get("report", "Fizik analizi tamamlandı efendim.")
        intent = "coaching_advice"
    elif analysis.get("clarify_message"):
        jarvis_reply = analysis["clarify_message"]
        intent = "chat"
    else:
        jarvis_reply = "Fotoğrafı analiz edemedim efendim. Daha net bir görüntü dener misin?"
        intent = "chat"

    crud.save_chat_message(db, "jarvis", jarvis_reply, intent=intent, session_id=session_id)
    return schemas.ChatResponse(intent=intent, jarvis_reply=jarvis_reply, media_type="photo")


@app.post("/api/chat/video", response_model=schemas.ChatResponse)
async def chat_video(
    file: UploadFile = File(...),
    session_id: str = "default",
    db: Session = Depends(get_db),
):
    """Jarvis sohbetine video gönder — fizik/form analizi yapılır."""
    video_bytes = await file.read()
    if not video_bytes:
        raise HTTPException(status_code=400, detail="Boş video dosyası.")
    if len(video_bytes) > MAX_CHAT_MEDIA_BYTES:
        raise HTTPException(status_code=413, detail="Video çok büyük. 15-20 saniyelik kısa bir video dener misin?")
    mime_type = file.content_type or "video/webm"
    crud.save_chat_message(db, "user", "🎬 Video gönderildi", session_id=session_id)

    try:
        analysis = ai_core.analyze_physique_media(video_bytes, mime_type, db)
        jarvis_reply = analysis.get("report", "Video analizi tamamlandı efendim.")
        intent = "coaching_advice"
        crud.save_chat_message(db, "jarvis", jarvis_reply, intent=intent, session_id=session_id)
        return schemas.ChatResponse(
            intent=intent,
            jarvis_reply=jarvis_reply,
            media_type="video",
            training_advice=analysis.get("training_instruction"),
        )
    except Exception as e:
        logger.error(f"[CHAT] Video analizi hatası: {e}")
        raise HTTPException(status_code=500, detail=f"Video analiz edilemedi: {e}")


@app.get("/api/jarvis/briefing")
def get_jarvis_briefing(db: Session = Depends(get_db)):
    """Proaktif durum özeti — chat sekmesi açıldığında gösterilir."""
    return jarvis_brain.generate_proactive_briefing(db)


@app.post("/api/jarvis/checkin")
def jarvis_daily_checkin(body: schemas.CheckInRequest, db: Session = Depends(get_db)):
    """Yapılandırılmış günlük check-in."""
    result = jarvis_brain.process_checkin(
        db,
        mood=body.mood,
        energy=body.energy,
        sleep_quality=body.sleep_quality,
        soreness=body.soreness,
        notes=body.notes,
    )
    return result


@app.get("/api/memory")
def list_memories(category: str = None, db: Session = Depends(get_db)):
    """Jarvis hafıza paneli — tüm kayıtlar."""
    memories = crud.get_all_memories(db, category=category)
    return [
        schemas.UserMemoryResponse.model_validate(m) for m in memories
    ]


@app.get("/api/memory/search")
def search_memory(q: str, limit: int = 20, db: Session = Depends(get_db)):
    results = crud.search_memories(db, q, limit=limit)
    return [schemas.UserMemoryResponse.model_validate(m) for m in results]


@app.put("/api/memory/{memory_id}", response_model=schemas.UserMemoryResponse)
def update_memory(memory_id: int, body: schemas.UserMemoryUpdate, db: Session = Depends(get_db)):
    mem = crud.update_memory(db, memory_id, content=body.content, category=body.category, importance=body.importance)
    if not mem:
        raise HTTPException(status_code=404, detail="Hafıza kaydı bulunamadı.")
    return mem


@app.delete("/api/memory/{memory_id}")
def delete_memory(memory_id: int, db: Session = Depends(get_db)):
    if crud.delete_memory(db, memory_id):
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Hafıza kaydı bulunamadı.")


# ==========================================
# GELİŞİM GRAFİKLERİ (birleşik veri)
# ==========================================
@app.get("/api/progress/charts")
def get_progress_charts(days: int = None, db: Session = Depends(get_db)):
    """Dashboard gelişim sekmesi için birleşik grafik verisi.
    Varsayılan olarak kullanıcının platforma başladığı günden bugüne kadar veri döner."""
    profile = crud.get_or_create_profile(db)

    if profile.started_at:
        start_date = profile.started_at.date() if hasattr(profile.started_at, 'date') else profile.started_at
        period_days = max((date.today() - start_date).days, 1)
    else:
        period_days = days or 14

    metrics = crud.get_body_metrics(db, days=period_days)
    nutrition_history = crud.get_nutrition_history(db, days=period_days)
    volume = crud.get_weekly_volume_by_muscle_group(db, days=period_days)
    meal_plan = crud.get_meal_plan(db)

    if meal_plan:
        planned_cal = sum(m.calories for m in meal_plan)
        planned_prot = sum(m.protein for m in meal_plan)
    else:
        planned_cal = profile.daily_calorie_target or 2200
        planned_prot = profile.daily_protein_target or 140

    started_at_iso = profile.started_at.isoformat() if profile.started_at else None

    return {
        "weight": [{"date": str(m.date), "weight": m.weight} for m in metrics if m.weight],
        "nutrition": nutrition_history,
        "volume": [{"muscle_group": k, "sets": v} for k, v in sorted(volume.items(), key=lambda x: -x[1])],
        "targets": {
            "calories": planned_cal,
            "protein": planned_prot,
        },
        "period_days": period_days,
        "started_at": started_at_iso,
        "user_name": profile.name,
    }


# ==========================================
# BESLENME PLANI (AI önerisi - "ne yemelisin")
# ==========================================
@app.get("/api/mealplan", response_model=list[schemas.MealPlanItemResponse])
def get_meal_plan(db: Session = Depends(get_db)):
    return crud.get_meal_plan(db)


@app.post("/api/mealplan/generate", response_model=list[schemas.MealPlanItemResponse])
def regenerate_meal_plan(db: Session = Depends(get_db)):
    """Dashboard'dan 'Yeni Plan Oluştur' butonuyla tetiklenir."""
    return ai_core.generate_meal_plan(db)


@app.delete("/api/mealplan")
def delete_meal_plan(db: Session = Depends(get_db)):
    crud.clear_meal_plan(db)
    return {"status": "deleted"}


# ==========================================
# ANTRENMAN (frontend /api/workout -> aktif program bekliyor)
# ==========================================
@app.get("/api/workout")
def get_workout(db: Session = Depends(get_db)):
    programs = crud.get_workout_programs(db)
    today_logs = crud.get_workout_logs_by_date(db, date.today())
    suggestions_by_exercise = {s["exercise_name"].lower(): s for s in progression.get_all_suggestions(db)}
    return {
        "programs": [
            {
                "id": p.id,
                "day_name": p.day_name,
                "exercises": [
                    {
                        "id": e.id, "name": e.name, "target_sets": e.target_sets, "target_reps": e.target_reps,
                        "progression": suggestions_by_exercise.get(e.name.lower()),
                    }
                    for e in p.exercises
                ],
            }
            for p in programs
        ],
        "today_logs": [
            {"exercise_name": l.exercise_name, "set_number": l.set_number, "weight_lifted": l.weight_lifted, "reps_done": l.reps_done}
            for l in today_logs
        ],
    }


@app.get("/api/workout/day")
def get_workout_for_day(day: str, db: Session = Depends(get_db)):
    """Belirli bir güne ait antrenman penceresi. 'day' formatı: YYYY-MM-DD."""
    try:
        target_date = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz tarih formatı, YYYY-MM-DD kullan.")

    logs = crud.get_workout_logs_by_date(db, target_date)
    return {
        "date": day,
        "logs": [
            {"exercise_name": l.exercise_name, "set_number": l.set_number, "weight_lifted": l.weight_lifted, "reps_done": l.reps_done, "rpe": l.rpe}
            for l in logs
        ],
        "total_sets": len(logs),
    }


@app.get("/api/workout/progression")
def get_progression_suggestions(db: Session = Depends(get_db)):
    """Aktif programdaki her hareket için son antrenmana göre ağırlık/tekrar önerisi.
    Kural tabanlı (deterministik) progressive overload mantığı - AI yorumu değil."""
    return progression.get_all_suggestions(db)


@app.get("/api/workout/deload")
def get_deload_status(db: Session = Depends(get_db)):
    """Son antrenmanlara bakarak deload (hafifletme haftası) gerekip gerekmediğini döndürür."""
    return progression.check_deload_needed(db)


@app.get("/api/workout/volume")
def get_weekly_volume(days: int = 7, db: Session = Depends(get_db)):
    """Kas grubu başına son N gündeki toplam set sayısı - haftalık hacim takibi."""
    return crud.get_weekly_volume_by_muscle_group(db, days=days)


@app.get("/api/workout/heatmap")
def get_muscle_heatmap(days: int = 7, db: Session = Depends(get_db)):
    """Isı haritası için kas grubu başına set + tekrar sayısı."""
    return crud.get_muscle_group_intensity(db, days=days)


@app.get("/api/workout/heatmap/day")
def get_muscle_heatmap_for_day(day: str, db: Session = Depends(get_db)):
    """Belirli bir GÜNE ait ısı haritası - GÜNLÜK pencerede kullanılır."""
    try:
        target_date = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz tarih formatı, YYYY-MM-DD kullan.")
    return crud.get_muscle_group_intensity_for_date(db, target_date)


@app.post("/api/workout/program", response_model=schemas.WorkoutProgramResponse)
def create_program(program: schemas.WorkoutProgramCreate, db: Session = Depends(get_db)):
    return crud.create_workout_program(db, program)


@app.post("/api/workout/program/generate")
def generate_program_ai(db: Session = Depends(get_db)):
    """AI'nin profile göre sıfırdan haftalık program oluşturmasını tetikler."""
    programs = ai_core.generate_workout_program(db)
    return crud.get_workout_programs(db) if programs else []


@app.post("/api/workout/log", response_model=schemas.WorkoutLogResponse)
def log_set(log: schemas.WorkoutLogCreate, db: Session = Depends(get_db)):
    return crud.log_workout_set(db, log)


# ==========================================
# VÜCUT ÖLÇÜMÜ (gelişim takibi)
# ==========================================
@app.post("/api/metrics", response_model=schemas.BodyMetricResponse)
def add_body_metric(data: schemas.BodyMetricCreate, db: Session = Depends(get_db)):
    return crud.create_body_metric(db, data)


@app.get("/api/metrics")
def list_body_metrics(days: int = 60, db: Session = Depends(get_db)):
    return crud.get_body_metrics(db, days=days)


# ==========================================
# AI İÇGÖRÜLERİ / HAFTALIK ANALİZ
# ==========================================
@app.get("/api/insights")
def get_insights(db: Session = Depends(get_db)):
    memories = crud.get_recent_memories(db, limit=15)
    return [{"id": m.id, "category": m.category, "content": m.content, "created_at": m.created_at} for m in memories]


@app.post("/api/insights/generate")
def trigger_weekly_analysis(db: Session = Depends(get_db)):
    """Dashboard'dan manuel olarak 'Analiz Et' butonuna basınca tetiklenebilir."""
    analysis = ai_core.generate_weekly_analysis(db)
    return {"analysis": analysis}
