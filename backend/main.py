import os
import logging
import datetime as dt

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date

import models, schemas, crud, ai_core, progression
from database import SessionLocal, engine, get_db

logger = logging.getLogger(__name__)

models.Base.metadata.create_all(bind=engine)

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
    updates = data.model_dump(exclude_unset=True)
    updates["onboarding_completed"] = True
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
