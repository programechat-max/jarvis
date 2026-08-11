from pydantic import BaseModel
from typing import List, Optional
from datetime import date, datetime

# --- PROFİL ŞEMALARI ---
class UserProfileBase(BaseModel):
    age: Optional[int] = None
    height: Optional[float] = None
    current_weight: Optional[float] = None
    target_weight: Optional[float] = None
    goal: Optional[str] = None
    target_physique: Optional[str] = None
    experience_months: Optional[int] = None
    focus_muscle_group: Optional[str] = None
    activity_level: Optional[str] = None
    dietary_notes: Optional[str] = None
    schedule_notes: Optional[str] = None
    injury_notes: Optional[str] = None
    daily_calorie_target: Optional[float] = None
    daily_protein_target: Optional[float] = None
    daily_carb_target: Optional[float] = None
    daily_fat_target: Optional[float] = None
    onboarding_completed: Optional[bool] = None

class UserProfileResponse(UserProfileBase):
    id: int
    class Config:
        from_attributes = True

# --- HAREKET VE PROGRAM ŞEMALARI ---
class ExerciseBase(BaseModel):
    name: str
    target_sets: int
    target_reps: str
    muscle_group: Optional[str] = None

class ExerciseCreate(ExerciseBase):
    pass

class ExerciseResponse(ExerciseBase):
    id: int
    program_id: int
    class Config:
        from_attributes = True

class WorkoutProgramBase(BaseModel):
    day_name: str
    is_active: bool = True

class WorkoutProgramCreate(WorkoutProgramBase):
    exercises: List[ExerciseCreate]

class WorkoutProgramResponse(WorkoutProgramBase):
    id: int
    exercises: List[ExerciseResponse]
    class Config:
        from_attributes = True

# --- ANTRENMAN LOG ŞEMALARI ---
class WorkoutLogCreate(BaseModel):
    exercise_name: str
    set_number: int
    weight_lifted: float
    reps_done: int
    rpe: Optional[int] = None

class WorkoutLogResponse(WorkoutLogCreate):
    id: int
    date: date
    class Config:
        from_attributes = True

# --- BESLENME LOG ŞEMALARI ---
class NutritionLogCreate(BaseModel):
    meal_name: str
    time_target: Optional[str] = None
    ingredients: Optional[str] = None
    protein: float = 0.0
    carbs: float = 0.0
    fats: float = 0.0
    calories: float = 0.0

class NutritionLogResponse(NutritionLogCreate):
    id: int
    date: date
    class Config:
        from_attributes = True

# --- VÜCUT ÖLÇÜMÜ ŞEMALARI ---
class BodyMetricCreate(BaseModel):
    weight: Optional[float] = None
    waist: Optional[float] = None
    chest: Optional[float] = None
    arm: Optional[float] = None
    sleep_hours: Optional[float] = None
    note: Optional[str] = None

class BodyMetricResponse(BodyMetricCreate):
    id: int
    date: date
    class Config:
        from_attributes = True

# --- HAFIZA / İÇGÖRÜ ŞEMALARI ---
class UserMemoryCreate(BaseModel):
    category: str = "note"
    content: str

class UserMemoryResponse(UserMemoryCreate):
    id: int
    created_at: datetime
    class Config:
        from_attributes = True


# --- ÖĞÜN PLANI ŞEMALARI (AI önerisi) ---
class MealPlanItemCreate(BaseModel):
    meal_name: str
    time_target: Optional[str] = None
    description: Optional[str] = None
    calories: float = 0.0
    protein: float = 0.0
    carbs: float = 0.0
    fats: float = 0.0

class MealPlanItemResponse(MealPlanItemCreate):
    id: int
    created_at: datetime
    class Config:
        from_attributes = True
