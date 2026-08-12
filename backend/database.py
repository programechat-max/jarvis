import datetime
import logging
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

# SQLite Veritabanı Yolu
SQLALCHEMY_DATABASE_URL = "sqlite:///./sql_app.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Modellerin türeyeceği Base sınıfı
Base = declarative_base()


def migrate_schema():
    """Mevcut SQLite DB'ye yeni kolonları güvenli şekilde ekler."""
    import models  # noqa: F401 — tabloları register et

    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    if "user_profile" in table_names:
        existing_profile = {col["name"] for col in inspector.get_columns("user_profile")}
        profile_alters = []
        if "name" not in existing_profile:
            profile_alters.append("ALTER TABLE user_profile ADD COLUMN name VARCHAR")
        if "started_at" not in existing_profile:
            profile_alters.append("ALTER TABLE user_profile ADD COLUMN started_at DATETIME")
        if profile_alters:
            with engine.begin() as conn:
                for stmt in profile_alters:
                    conn.execute(text(stmt))
                # Mevcut kullanıcılar için started_at = updated_at veya şimdi
                conn.execute(text(
                    "UPDATE user_profile SET started_at = COALESCE(updated_at, datetime('now')) "
                    "WHERE started_at IS NULL"
                ))
            logger.info("user_profile şeması güncellendi (%d kolon)", len(profile_alters))

    if "user_memory" not in table_names:
        return
    existing = {col["name"] for col in inspector.get_columns("user_memory")}
    alters = []
    if "importance" not in existing:
        alters.append("ALTER TABLE user_memory ADD COLUMN importance INTEGER DEFAULT 5")
    if "keywords" not in existing:
        alters.append("ALTER TABLE user_memory ADD COLUMN keywords VARCHAR DEFAULT ''")
    if "memory_key" not in existing:
        alters.append("ALTER TABLE user_memory ADD COLUMN memory_key VARCHAR")
    if "access_count" not in existing:
        alters.append("ALTER TABLE user_memory ADD COLUMN access_count INTEGER DEFAULT 0")
    if "updated_at" not in existing:
        alters.append("ALTER TABLE user_memory ADD COLUMN updated_at DATETIME")
    if alters:
        with engine.begin() as conn:
            for stmt in alters:
                conn.execute(text(stmt))
        logger.info("user_memory şeması güncellendi (%d kolon)", len(alters))


def get_db():
    """FastAPI router'ları için veritabanı oturumu sağlar."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_date():
    """Bugünün tarihini ISO formatında (YIL-AY-GÜN) döndürür."""
    return datetime.date.today().isoformat()


def get_todays_nutrition_summary():
    """Bugünün toplam kalori ve protein miktarını hesaplayıp döndürür.
    Telegram botunun akşam kontrolü için kullanılır."""
    import models
    from datetime import date
    db = SessionLocal()
    try:
        today = date.today()
        meals = db.query(models.NutritionLog).filter(models.NutritionLog.date == today).all()

        total_cals = sum(m.calories for m in meals if m.calories)
        total_protein = sum(m.protein for m in meals if m.protein)

        return {"calories": total_cals, "protein": total_protein}
    except Exception as e:
        print(f"[VERİTABANI ÖZET HATASI]: {e}")
        return {"calories": 0, "protein": 0}
    finally:
        db.close()


def delete_nutrition_meal(meal_name):
    """Telegram'dan gelen isme göre bugüne ait en son eşleşen öğünü siler."""
    import models
    from datetime import date
    db = SessionLocal()
    try:
        meal = (
            db.query(models.NutritionLog)
            .filter(models.NutritionLog.meal_name.like(f"%{meal_name}%"))
            .filter(models.NutritionLog.date == date.today())
            .order_by(models.NutritionLog.id.desc())
            .first()
        )
        if meal:
            db.delete(meal)
            db.commit()
            return True
        return False
    except Exception as e:
        print(f"[VERİTABANI SİLME HATASI]: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def edit_nutrition_meal(meal_name, calories, protein, carbs, fats, description=None):
    """Mevcut (bugünkü) bir öğünün makro ve kalori değerlerini günceller."""
    import models
    from datetime import date
    db = SessionLocal()
    try:
        meal = (
            db.query(models.NutritionLog)
            .filter(models.NutritionLog.meal_name.like(f"%{meal_name}%"))
            .filter(models.NutritionLog.date == date.today())
            .order_by(models.NutritionLog.id.desc())
            .first()
        )
        if meal:
            if calories is not None: meal.calories = float(calories)
            if protein is not None: meal.protein = float(protein)
            if carbs is not None: meal.carbs = float(carbs)
            if fats is not None: meal.fats = float(fats)
            if description is not None: meal.ingredients = description
            db.commit()
            return True
        return False
    except Exception as e:
        print(f"[VERİTABANI GÜNCELLEME HATASI]: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def upsert_nutrition(date_val, meal_name, description, calories, protein, carbs, fats):
    """Telegram'dan gelen makro verilerini SQLite veritabanına kaydeder."""
    import models
    db = SessionLocal()
    try:
        new_meal = models.NutritionLog(
            meal_name=meal_name,
            time_target=datetime.datetime.now().strftime("%H:%M"),
            ingredients=description,
            protein=protein,
            carbs=carbs,
            fats=fats,
            calories=calories,
        )
        db.add(new_meal)
        db.commit()
        return True
    except Exception as e:
        print(f"[VERİTABANI HATASI]: {e}")
        db.rollback()
        return False
    finally:
        db.close()
