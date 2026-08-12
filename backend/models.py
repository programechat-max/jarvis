from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, Text, DateTime, Date
from sqlalchemy.orm import relationship
import datetime

from database import Base


class UserProfile(Base):
    """Kullanıcının kişisel profili, hedefleri ve yaşam tarzı bilgileri.
    Tek kullanıcılı sistem olduğu için tek satır tutulur (id=1)."""
    __tablename__ = "user_profile"
    id = Column(Integer, primary_key=True, index=True)

    # Fiziksel bilgiler
    age = Column(Integer, nullable=True)
    height = Column(Float, nullable=True)
    current_weight = Column(Float, nullable=True)
    target_weight = Column(Float, nullable=True)

    # Hedef ve deneyim
    goal = Column(String, default="recomp")  # bulk | cut | recomp | maintain
    target_physique = Column(String, default="")
    experience_months = Column(Integer, default=0)
    focus_muscle_group = Column(String, default="")

    # Yaşam tarzı (kişiselleştirme için kritik alanlar)
    activity_level = Column(String, default="moderate")  # sedentary|light|moderate|active
    dietary_notes = Column(Text, default="")   # sevdiği/sevmediği yiyecekler, alerjiler
    schedule_notes = Column(Text, default="")  # uyku/uyanma saatleri, iş/okul yoğunluğu
    injury_notes = Column(Text, default="")    # sakatlık/kısıtlama notları

    # AI tarafından hesaplanan / güncellenen günlük hedefler
    daily_calorie_target = Column(Float, default=2200.0)
    daily_protein_target = Column(Float, default=140.0)
    daily_carb_target = Column(Float, default=220.0)
    daily_fat_target = Column(Float, default=70.0)

    onboarding_completed = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class WorkoutProgram(Base):
    __tablename__ = "workout_programs"
    id = Column(Integer, primary_key=True, index=True)
    day_name = Column(String, index=True)  # Örn: "Pazartesi - Göğüs & Karın"
    is_active = Column(Boolean, default=True)

    exercises = relationship("Exercise", back_populates="program", cascade="all, delete-orphan")


class Exercise(Base):
    __tablename__ = "exercises"
    id = Column(Integer, primary_key=True, index=True)
    program_id = Column(Integer, ForeignKey("workout_programs.id"))
    name = Column(String)
    target_sets = Column(Integer)
    target_reps = Column(String)  # Örn: "8-12"
    muscle_group = Column(String, nullable=True)  # Örn: "Göğüs", "Sırt", "Bacak" - hacim takibi için

    program = relationship("WorkoutProgram", back_populates="exercises")


class WorkoutLog(Base):
    """Gerçekte yapılan set bazlı antrenman kayıtları."""
    __tablename__ = "workout_logs"
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, default=datetime.date.today, index=True)
    exercise_name = Column(String)
    set_number = Column(Integer)
    weight_lifted = Column(Float)
    reps_done = Column(Integer)
    rpe = Column(Integer, nullable=True)  # Zorluk derecesi (1-10)


class NutritionLog(Base):
    """Telegram'dan raporlanan gerçek öğün kayıtları (günlük)."""
    __tablename__ = "nutrition_logs"
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, default=datetime.date.today, index=True)
    meal_name = Column(String)
    time_target = Column(String)
    ingredients = Column(Text)
    protein = Column(Float, default=0.0)
    carbs = Column(Float, default=0.0)
    fats = Column(Float, default=0.0)
    calories = Column(Float, default=0.0)


class BodyMetric(Base):
    """Kilo ve vücut ölçümü geçmişi - gelişim takibi için."""
    __tablename__ = "body_metrics"
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, default=datetime.date.today, index=True)
    weight = Column(Float, nullable=True)
    waist = Column(Float, nullable=True)
    chest = Column(Float, nullable=True)
    arm = Column(Float, nullable=True)
    sleep_hours = Column(Float, nullable=True)
    note = Column(Text, nullable=True)


class UserMemory(Base):
    """AI'nin kullanıcı hakkında öğrendiği kalıcı bilgiler / haftalık analiz sonuçları.
    Bu tablo Jarvis'in 'kullanıcıyı keşfetmesini' ve zamanla kişiselleşmesini sağlar."""
    __tablename__ = "user_memory"
    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    category = Column(String, default="note")  # preference | insight | analysis | note
    content = Column(Text)


class MealPlanItem(Base):
    """AI tarafından oluşturulan, GÜNÜN önerilen öğün planı.
    NutritionLog'dan farkı: bu 'ne yemelisin' (öneri), NutritionLog ise 'ne yedin' (gerçek kayıt)."""
    __tablename__ = "meal_plan_items"
    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    meal_name = Column(String)       # "Kahvaltı", "Öğle Yemeği" vb.
    time_target = Column(String)     # "08:00"
    description = Column(Text)       # önerilen içerik
    calories = Column(Float, default=0.0)
    protein = Column(Float, default=0.0)
    carbs = Column(Float, default=0.0)
    fats = Column(Float, default=0.0)
