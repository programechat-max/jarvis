import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

_DB_PATH = Path(__file__).resolve().parent / "sql_app.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{_DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Modellerin türeyeceği Base sınıfı
Base = declarative_base()


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
