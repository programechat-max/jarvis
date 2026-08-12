from sqlalchemy.orm import Session
from sqlalchemy import func
import datetime
from datetime import date, timedelta
import models, schemas

# ==========================================
# 0. PROFİL OPERASYONLARI (Kişiselleştirme)
# ==========================================
def get_or_create_profile(db: Session) -> models.UserProfile:
    """Tek kullanıcılı sistem - profil yoksa boş bir tane oluşturur."""
    profile = db.query(models.UserProfile).first()
    if not profile:
        profile = models.UserProfile()
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def update_profile(db: Session, data: dict) -> models.UserProfile:
    profile = get_or_create_profile(db)
    for key, value in data.items():
        if value is not None and hasattr(profile, key):
            setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile


# ==========================================
# 1. BESLENME OPERASYONLARI
# ==========================================
def get_nutrition_logs_by_date(db: Session, target_date: date):
    return db.query(models.NutritionLog).filter(models.NutritionLog.date == target_date).all()


def get_nutrition_history(db: Session, days: int = 7):
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    logs = db.query(models.NutritionLog).filter(
        models.NutritionLog.date >= start_date,
        models.NutritionLog.date <= end_date,
    ).all()

    history = {}
    for i in range(days + 1):
        d = str(start_date + timedelta(days=i))
        history[d] = {"calories": 0.0, "protein": 0.0}

    for log in logs:
        d = str(log.date)
        if d in history:
            history[d]["calories"] += (log.calories or 0)
            history[d]["protein"] += (log.protein or 0)

    return [{"date": k, **v} for k, v in history.items()]


def create_nutrition_log(db: Session, log: schemas.NutritionLogCreate):
    db_log = models.NutritionLog(**log.model_dump())
    db.add(db_log)
    db.commit()
    db.refresh(db_log)
    return db_log


def clear_nutrition_logs_by_date(db: Session, target_date: date):
    """Belirli bir güne ait TÜM gerçek yemek kayıtlarını siler (plan değil, gerçek girdi)."""
    deleted = db.query(models.NutritionLog).filter(models.NutritionLog.date == target_date).delete()
    db.commit()
    return deleted


# ==========================================
# 2. ANTRENMAN OPERASYONLARI
# ==========================================
def get_workout_programs(db: Session):
    return db.query(models.WorkoutProgram).filter(models.WorkoutProgram.is_active == True).all()


def create_workout_program(db: Session, program: schemas.WorkoutProgramCreate):
    db_program = models.WorkoutProgram(day_name=program.day_name, is_active=program.is_active)
    db.add(db_program)
    db.commit()
    db.refresh(db_program)

    for ex in program.exercises:
        db_ex = models.Exercise(**ex.model_dump(), program_id=db_program.id)
        db.add(db_ex)

    db.commit()
    db.refresh(db_program)
    return db_program


def clear_workout_programs(db: Session):
    """Mevcut tüm programları ve hareketlerini siler. NOT: WorkoutProgram.exercises'daki
    cascade='all, delete-orphan' tanımı sadece session.delete() ile ORM üzerinden silme
    yapılırken tetiklenir - toplu (bulk) Query.delete() bunu ATLAR ve alt tablodaki
    (Exercise) satırları yetim olarak veritabanında bırakır. Bu yüzden önce Exercise'ları,
    sonra WorkoutProgram'ları açıkça siliyoruz."""
    db.query(models.Exercise).delete()
    db.query(models.WorkoutProgram).delete()
    db.commit()


def log_workout_set(db: Session, log_data: schemas.WorkoutLogCreate):
    db_log = models.WorkoutLog(**log_data.model_dump())
    db.add(db_log)
    db.commit()
    db.refresh(db_log)
    return db_log


def get_max_weight_for_exercise(db: Session, exercise_name: str, exclude_log_id: int = None):
    """Bir hareket için bugüne kadar kaydedilmiş en yüksek ağırlığı döndürür (PR karşılaştırması için).
    exclude_log_id verilirse o kaydı hariç tutar (yeni girilen setin kendisiyle karşılaştırmaması için)."""
    q = db.query(func.max(models.WorkoutLog.weight_lifted)).filter(
        func.lower(models.WorkoutLog.exercise_name) == exercise_name.lower()
    )
    if exclude_log_id:
        q = q.filter(models.WorkoutLog.id != exclude_log_id)
    result = q.scalar()
    return result or 0


def get_workout_logs_by_date(db: Session, target_date: date):
    return db.query(models.WorkoutLog).filter(models.WorkoutLog.date == target_date).order_by(models.WorkoutLog.id).all()


def get_workout_logs_range(db: Session, days: int = 14):
    start_date = date.today() - timedelta(days=days)
    return db.query(models.WorkoutLog).filter(models.WorkoutLog.date >= start_date).all()


def get_weekly_volume_by_muscle_group(db: Session, days: int = 7):
    """Son N gündeki setleri, aktif programdaki hareket isimlerini kas grubuna eşleyerek
    kas grubu başına toplam set sayısını hesaplar. Programda olmayan/eşleşmeyen hareketler
    'Diğer' grubuna düşer."""
    exercises = db.query(models.Exercise).all()
    name_to_group = {e.name.strip().lower(): (e.muscle_group or "Diğer") for e in exercises}

    logs = get_workout_logs_range(db, days=days)
    volume = {}
    for log in logs:
        group = name_to_group.get(log.exercise_name.strip().lower(), "Diğer")
        volume[group] = volume.get(group, 0) + 1
    return volume


def get_muscle_group_intensity(db: Session, days: int = 7):
    """Isı haritası için: kas grubu başına set sayısı VE toplam tekrar sayısını hesaplar.
    Set sayısı, hipertrofi hacmi takibinde standart ölçüdür; tekrar sayısı ek bağlam verir.
    Dönen değer: {grup: {"sets": int, "reps": int}}"""
    exercises = db.query(models.Exercise).all()
    name_to_group = {e.name.strip().lower(): (e.muscle_group or "Diğer") for e in exercises}

    logs = get_workout_logs_range(db, days=days)
    intensity = {}
    for log in logs:
        group = name_to_group.get(log.exercise_name.strip().lower(), "Diğer")
        if group not in intensity:
            intensity[group] = {"sets": 0, "reps": 0}
        intensity[group]["sets"] += 1
        intensity[group]["reps"] += (log.reps_done or 0)
    return intensity


def get_muscle_group_intensity_for_date(db: Session, target_date: date):
    """Isı haritasının GÜNLÜK versiyonu - sadece belirtilen tek güne ait setleri kas
    grubuna göre toplar (haftalık ortalama değil, o günün gerçek antrenmanı)."""
    exercises = db.query(models.Exercise).all()
    name_to_group = {e.name.strip().lower(): (e.muscle_group or "Diğer") for e in exercises}

    logs = get_workout_logs_by_date(db, target_date)
    intensity = {}
    for log in logs:
        group = name_to_group.get(log.exercise_name.strip().lower(), "Diğer")
        if group not in intensity:
            intensity[group] = {"sets": 0, "reps": 0}
        intensity[group]["sets"] += 1
        intensity[group]["reps"] += (log.reps_done or 0)
    return intensity


def get_recent_sessions_for_exercise(db: Session, exercise_name: str, session_count: int = 3):
    """Bir hareket için son N farklı antrenman GÜNÜNE ait setleri döndürür (deload tespiti için).
    Dönen değer: {tarih: [set1, set2, ...], ...} - en yeniden en eskiye sıralı."""
    all_logs = (
        db.query(models.WorkoutLog)
        .filter(func.lower(models.WorkoutLog.exercise_name) == exercise_name.lower())
        .order_by(models.WorkoutLog.date.desc(), models.WorkoutLog.id)
        .all()
    )
    sessions = {}
    for log in all_logs:
        sessions.setdefault(log.date, []).append(log)
        if len(sessions) > session_count:
            break
    # Son session_count kadarını al (fazladan eklenen son günü at)
    ordered_dates = sorted(sessions.keys(), reverse=True)[:session_count]
    return {d: sessions[d] for d in ordered_dates}


def get_last_session_logs_for_exercise(db: Session, exercise_name: str):
    """Bir hareket için en son yapıldığı GÜNE ait tüm setleri döndürür.
    Progressive overload önerisi bunun üzerinden hesaplanır."""
    last_log = (
        db.query(models.WorkoutLog)
        .filter(func.lower(models.WorkoutLog.exercise_name) == exercise_name.lower())
        .order_by(models.WorkoutLog.date.desc(), models.WorkoutLog.id.desc())
        .first()
    )
    if not last_log:
        return []
    return (
        db.query(models.WorkoutLog)
        .filter(models.WorkoutLog.exercise_name == last_log.exercise_name)
        .filter(models.WorkoutLog.date == last_log.date)
        .order_by(models.WorkoutLog.set_number)
        .all()
    )


# ==========================================
# 3. VÜCUT ÖLÇÜMÜ OPERASYONLARI (Gelişim takibi)
# ==========================================
def create_body_metric(db: Session, data: schemas.BodyMetricCreate):
    db_metric = models.BodyMetric(**data.model_dump())
    db.add(db_metric)
    db.commit()
    db.refresh(db_metric)
    # Kilo girildiyse profildeki current_weight'i de güncelle
    if data.weight:
        profile = get_or_create_profile(db)
        profile.current_weight = data.weight
        db.commit()
    return db_metric


def get_body_metrics(db: Session, days: int = 60):
    start_date = date.today() - timedelta(days=days)
    return db.query(models.BodyMetric).filter(models.BodyMetric.date >= start_date).order_by(models.BodyMetric.date).all()


# ==========================================
# 4. HAFIZA / İÇGÖRÜ OPERASYONLARI (AI'nin kullanıcıyı keşfetmesi)
# ==========================================
# Kaç adet "analysis" (haftalık analiz raporu) kaydı saklanacak. Bu kategori tek başına
# uzun metinler ürettiği için sınırsız birikmesine izin verilirse (eskiden öyleydi),
# birkaç hafta içinde get_recent_memories'in döndürdüğü sınırlı sayıdaki kaydı tamamen
# doldurup kullanıcının asıl önemli olan preference/note kayıtlarını ("balık yemem" gibi)
# hafızadan dışarı iter. Sadece en güncel analizler tutulur, gerisi otomatik budanır.
MAX_ANALYSIS_MEMORIES = 2

# preference/insight/note kategorilerinden hafızaya kaç kayıt taşınacak. Bunlar kısa
# metinler olduğu için analiz raporlarına göre çok daha fazlasını tutmak ucuz ve faydalı -
# eskiden TÜM kategoriler karışık halde sadece son 10 kayıt çekiliyordu, bu da birkaç
# günlük sohbetten sonra eski ama hâlâ geçerli tercihlerin unutulmasına yol açıyordu.
MAX_DURABLE_MEMORIES = 40


def _normalize_memory_text(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def create_memory(db: Session, category: str, content: str, importance: int = 5, keywords: str = "", memory_key: str = None):
    """Yeni bir hafıza kaydı ekler. memory_key varsa aynı anahtardaki kaydı günceller."""
    normalized_new = _normalize_memory_text(content)

    if memory_key:
        existing_by_key = (
            db.query(models.UserMemory)
            .filter(models.UserMemory.memory_key == memory_key)
            .first()
        )
        if existing_by_key:
            existing_by_key.content = content
            existing_by_key.category = category
            existing_by_key.importance = max(existing_by_key.importance or 5, importance)
            if keywords:
                existing_by_key.keywords = keywords
            existing_by_key.updated_at = datetime.datetime.utcnow()
            db.commit()
            db.refresh(existing_by_key)
            return existing_by_key

    existing = (
        db.query(models.UserMemory)
        .filter(models.UserMemory.category == category)
        .order_by(models.UserMemory.id.desc())
        .limit(200)
        .all()
    )
    for mem in existing:
        normalized_existing = _normalize_memory_text(mem.content)
        if not normalized_existing or not normalized_new:
            continue
        if normalized_existing == normalized_new or normalized_existing in normalized_new or normalized_new in normalized_existing:
            mem.content = content
            mem.importance = max(mem.importance or 5, importance)
            if keywords:
                mem.keywords = keywords
            if memory_key:
                mem.memory_key = memory_key
            mem.updated_at = datetime.datetime.utcnow()
            db.commit()
            db.refresh(mem)
            return mem

    db_mem = models.UserMemory(
        category=category,
        content=content,
        importance=importance,
        keywords=keywords or "",
        memory_key=memory_key,
    )
    db.add(db_mem)
    db.commit()
    db.refresh(db_mem)

    if category == "analysis":
        old_analyses = (
            db.query(models.UserMemory)
            .filter(models.UserMemory.category == "analysis")
            .order_by(models.UserMemory.id.desc())
            .offset(MAX_ANALYSIS_MEMORIES)
            .all()
        )
        for old in old_analyses:
            db.delete(old)
        if old_analyses:
            db.commit()

    return db_mem


def forget_memory(db: Session, content_hint: str):
    """Kullanıcı 'bunu unut' dediğinde, hafızadaki kayıtlar arasından içerik olarak en
    yakın eşleşeni bulup SİLER. Basit bir metin benzerliği (ortak kelime sayısı) kullanır -
    tam eşleşme şartı aramaz, çünkü kullanıcı genelde kaydın kendisini birebir tekrar
    yazmaz, konuyu özetler (örn. kayıt: "dizinde eski bir sakatlık var", kullanıcı:
    "diz sakatlığımı unut")."""
    hint_words = set(_normalize_memory_text(content_hint).split())
    if not hint_words:
        return None

    candidates = db.query(models.UserMemory).all()
    best_match = None
    best_score = 0
    for mem in candidates:
        mem_words = set(_normalize_memory_text(mem.content).split())
        if not mem_words:
            continue
        overlap = len(hint_words & mem_words)
        if overlap > best_score:
            best_score = overlap
            best_match = mem

    # En az bir anlamlı kelime örtüşmesi olmadan silme yapma - yanlışlıkla alakasız bir
    # kaydı silmemek için.
    if best_match and best_score > 0:
        db.delete(best_match)
        db.commit()
        return best_match
    return None


def get_recent_memories(db: Session, limit: int = MAX_DURABLE_MEMORIES):
    """Hafızayı iki katmanlı çeker."""
    analyses = (
        db.query(models.UserMemory)
        .filter(models.UserMemory.category == "analysis")
        .order_by(models.UserMemory.id.desc())
        .limit(MAX_ANALYSIS_MEMORIES)
        .all()
    )
    durable = (
        db.query(models.UserMemory)
        .filter(models.UserMemory.category != "analysis")
        .order_by(models.UserMemory.id.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(durable)) + list(reversed(analyses))


def get_all_memories(db: Session, category: str = None):
    q = db.query(models.UserMemory).order_by(models.UserMemory.importance.desc(), models.UserMemory.id.desc())
    if category:
        q = q.filter(models.UserMemory.category == category)
    return q.all()


def update_memory(db: Session, memory_id: int, content: str = None, category: str = None, importance: int = None):
    mem = db.query(models.UserMemory).filter(models.UserMemory.id == memory_id).first()
    if not mem:
        return None
    if content is not None:
        mem.content = content
    if category is not None:
        mem.category = category
    if importance is not None:
        mem.importance = importance
    mem.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(mem)
    return mem


def delete_memory(db: Session, memory_id: int):
    mem = db.query(models.UserMemory).filter(models.UserMemory.id == memory_id).first()
    if mem:
        db.delete(mem)
        db.commit()
        return True
    return False


def search_memories(db: Session, query: str, limit: int = 20):
    """Basit anahtar kelime araması — hafıza paneli için."""
    words = [w for w in _normalize_memory_text(query).split() if len(w) > 2]
    if not words:
        return get_all_memories(db)[:limit]
    all_mem = db.query(models.UserMemory).all()
    scored = []
    for mem in all_mem:
        text = _normalize_memory_text(f"{mem.content} {mem.keywords or ''}")
        score = sum(1 for w in words if w in text)
        score += (mem.importance or 5) * 0.1
        if score > 0:
            scored.append((score, mem))
    scored.sort(key=lambda x: -x[0])
    return [m for _, m in scored[:limit]]


def touch_memory_access(db: Session, memory_ids: list):
    if not memory_ids:
        return
    db.query(models.UserMemory).filter(models.UserMemory.id.in_(memory_ids)).update(
        {models.UserMemory.access_count: models.UserMemory.access_count + 1},
        synchronize_session=False,
    )
    db.commit()


# ==========================================
# 6. SOHBET GEÇMİŞİ
# ==========================================
def save_chat_message(db: Session, role: str, content: str, intent: str = None, session_id: str = "default"):
    msg = models.ChatMessage(role=role, content=content, intent=intent, session_id=session_id)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    _trim_chat_history(db, session_id)
    return msg


def _trim_chat_history(db: Session, session_id: str, keep: int = 100):
    ids = (
        db.query(models.ChatMessage.id)
        .filter(models.ChatMessage.session_id == session_id)
        .order_by(models.ChatMessage.id.desc())
        .offset(keep)
        .all()
    )
    if ids:
        db.query(models.ChatMessage).filter(models.ChatMessage.id.in_([i[0] for i in ids])).delete(synchronize_session=False)
        db.commit()


def get_chat_history(db: Session, session_id: str = "default", limit: int = 30):
    rows = (
        db.query(models.ChatMessage)
        .filter(models.ChatMessage.session_id == session_id)
        .order_by(models.ChatMessage.id.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(rows))


def clear_chat_history(db: Session, session_id: str = "default"):
    deleted = db.query(models.ChatMessage).filter(models.ChatMessage.session_id == session_id).delete()
    db.commit()
    return deleted


# ==========================================
# 7. GÜNLÜK CHECK-IN
# ==========================================
def upsert_daily_checkin(db: Session, data: dict):
    today = date.today()
    checkin = db.query(models.DailyCheckIn).filter(models.DailyCheckIn.date == today).first()
    if not checkin:
        checkin = models.DailyCheckIn(date=today)
        db.add(checkin)
    for key, val in data.items():
        if val is not None and hasattr(checkin, key):
            setattr(checkin, key, val)
    db.commit()
    db.refresh(checkin)
    return checkin


def get_today_checkin(db: Session):
    return db.query(models.DailyCheckIn).filter(models.DailyCheckIn.date == date.today()).first()


def get_checkin_history(db: Session, days: int = 14):
    start = date.today() - timedelta(days=days)
    return db.query(models.DailyCheckIn).filter(models.DailyCheckIn.date >= start).order_by(models.DailyCheckIn.date).all()


# ==========================================
# 5. ÖĞÜN PLANI OPERASYONLARI (AI önerisi)
# ==========================================
def replace_meal_plan(db: Session, items: list[schemas.MealPlanItemCreate]):
    """Mevcut planı tamamen yeni planla değiştirir (tek aktif plan mantığı)."""
    db.query(models.MealPlanItem).delete()
    new_items = []
    for item in items:
        db_item = models.MealPlanItem(**item.model_dump())
        db.add(db_item)
        new_items.append(db_item)
    db.commit()
    for item in new_items:
        db.refresh(item)
    return new_items


def get_meal_plan(db: Session):
    return db.query(models.MealPlanItem).order_by(models.MealPlanItem.id).all()


def clear_meal_plan(db: Session):
    """Planı tamamen siler - AI'ye yeniden yazdırmadan, direkt boşaltır."""
    db.query(models.MealPlanItem).delete()
    db.commit()
