import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ReferenceLine, CartesianGrid,
} from 'recharts';

const API_BASE = 'http://127.0.0.1:8000';

const DATA_MUTATING_INTENTS = new Set([
  'log_food', 'complete_all_meals', 'log_workout', 'log_weight',
  'remember', 'forget', 'modify_meal_plan', 'delete_meal_plan',
  'delete_food_log', 'modify_workout_program', 'delete_workout_program',
]);

const PROGRESSION_ICON = { increase_weight: '📈', hold_weight: '⏸️', add_reps: '➕', unknown_range: '❔' };
const PROGRESSION_COLOR = {
  increase_weight: 'text-emerald-400',
  hold_weight: 'text-orange-400',
  add_reps: 'text-orange-300',
  unknown_range: 'text-neutral-500',
};

export default function DashboardMaster() {
  const [isSetupComplete, setIsSetupComplete] = useState(false);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('flow');

  const [profile, setProfile] = useState(null);
  const [nutritionPlans, setNutritionPlans] = useState([]);
  const [workout, setWorkout] = useState({ programs: [], today_logs: [] });
  const [metrics, setMetrics] = useState([]);
  const [insights, setInsights] = useState([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [weightInput, setWeightInput] = useState('');
  const [savingWeight, setSavingWeight] = useState(false);
  const [mealPlan, setMealPlan] = useState([]);
  const [deloadStatus, setDeloadStatus] = useState(null);
  const [selectedDate, setSelectedDate] = useState(() => new Date().toISOString().split('T')[0]);
  const [dailyNutrition, setDailyNutrition] = useState(null);
  const [dailyWorkout, setDailyWorkout] = useState(null);
  const [dailyHeatmap, setDailyHeatmap] = useState({});
  const [loadingDaily, setLoadingDaily] = useState(false);
  const [generatingPlan, setGeneratingPlan] = useState(false);
  const [generatingProgram, setGeneratingProgram] = useState(false);

  // Sprint 1: Jarvis chat
  const [chatMessages, setChatMessages] = useState([
    { role: 'jarvis', text: 'Merhaba efendim. Beslenme, antrenman veya hedefleriniz hakkında bana yazabilirsiniz.' },
  ]);
  const [chatInput, setChatInput] = useState('');
  const [chatSending, setChatSending] = useState(false);
  const chatEndRef = useRef(null);

  // Sprint 1: Gelişim grafikleri
  const [chartData, setChartData] = useState(null);
  const [loadingCharts, setLoadingCharts] = useState(false);

  // Sprint 1: Yemek fotoğrafı
  const [foodPhotoPreview, setFoodPhotoPreview] = useState(null);
  const [foodPhotoAnalyzing, setFoodPhotoAnalyzing] = useState(false);
  const [foodPhotoError, setFoodPhotoError] = useState('');
  const foodPhotoInputRef = useRef(null);

  // ==========================================
  // BACKEND'DEN VERİLERİ ÇEKEN MOTOR
  // ==========================================
  const fetchDashboardData = useCallback(async () => {
    try {
      const statusRes = await fetch(`${API_BASE}/api/status`);
      const statusData = await statusRes.json();
      setIsSetupComplete(statusData.is_setup_complete);

      if (statusData.is_setup_complete) {
        const [profileRes, nutritionRes, workoutRes, metricsRes, insightsRes, mealPlanRes, deloadRes] = await Promise.all([
          fetch(`${API_BASE}/api/profile`),
          fetch(`${API_BASE}/api/nutrition`),
          fetch(`${API_BASE}/api/workout`),
          fetch(`${API_BASE}/api/metrics?days=30`),
          fetch(`${API_BASE}/api/insights`),
          fetch(`${API_BASE}/api/mealplan`),
          fetch(`${API_BASE}/api/workout/deload`),
        ]);
        setProfile(await profileRes.json());
        setNutritionPlans(await nutritionRes.json());
        setWorkout(await workoutRes.json());
        setMetrics(await metricsRes.json());
        setInsights(await insightsRes.json());
        setMealPlan(await mealPlanRes.json());
        setDeloadStatus(await deloadRes.json());
      }
    } catch (error) {
      console.error("Backend bağlantı hatası:", error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDashboardData();
    const interval = setInterval(fetchDashboardData, 10000);
    return () => clearInterval(interval);
  }, [fetchDashboardData]);

  const fetchDailyWindow = useCallback(async (dateStr) => {
    setLoadingDaily(true);
    try {
      const [nutritionRes, workoutRes, heatmapRes] = await Promise.all([
        fetch(`${API_BASE}/api/nutrition/day?day=${dateStr}`),
        fetch(`${API_BASE}/api/workout/day?day=${dateStr}`),
        fetch(`${API_BASE}/api/workout/heatmap/day?day=${dateStr}`),
      ]);
      setDailyNutrition(await nutritionRes.json());
      setDailyWorkout(await workoutRes.json());
      setDailyHeatmap(await heatmapRes.json());
    } catch (error) {
      console.error("Günlük pencere hatası:", error);
    } finally {
      setLoadingDaily(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'daily') {
      fetchDailyWindow(selectedDate);
    }
  }, [activeTab, selectedDate, fetchDailyWindow]);

  const fetchChartData = useCallback(async () => {
    setLoadingCharts(true);
    try {
      const res = await fetch(`${API_BASE}/api/progress/charts?days=14`);
      setChartData(await res.json());
    } catch (e) {
      console.error('Grafik verisi alınamadı:', e);
    } finally {
      setLoadingCharts(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'progress') {
      fetchChartData();
    }
  }, [activeTab, fetchChartData]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  const sendChatMessage = async (e) => {
    e?.preventDefault();
    const text = chatInput.trim();
    if (!text || chatSending) return;
    setChatInput('');
    setChatMessages((prev) => [...prev, { role: 'user', text }]);
    setChatSending(true);
    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      if (!res.ok) throw new Error('chat failed');
      const data = await res.json();
      setChatMessages((prev) => [...prev, { role: 'jarvis', text: data.jarvis_reply, intent: data.intent }]);
      if (DATA_MUTATING_INTENTS.has(data.intent)) {
        fetchDashboardData();
        if (activeTab === 'progress') fetchChartData();
      }
    } catch (err) {
      console.error(err);
      setChatMessages((prev) => [...prev, { role: 'jarvis', text: 'Bağlantı hatası efendim, backend çalışıyor mu kontrol eder misiniz?' }]);
    } finally {
      setChatSending(false);
    }
  };

  const analyzeFoodPhoto = async (file) => {
    if (!file) return;
    setFoodPhotoError('');
    setFoodPhotoAnalyzing(true);
    setFoodPhotoPreview(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch(`${API_BASE}/api/nutrition/photo`, { method: 'POST', body: fd });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Analiz başarısız');
      }
      const result = await res.json();
      if (result.photo_type === 'food' && result.food) {
        setFoodPhotoPreview({ ...result.food, previewUrl: URL.createObjectURL(file) });
      } else if (result.photo_type === 'physique' && result.physique) {
        setFoodPhotoError('Bu bir yemek fotoğrafı değil — vücut/fizik fotoğrafı algılandı. Yemek tabağının fotoğrafını yükleyin.');
      } else {
        setFoodPhotoError(result.clarify_message || 'Yemek tanımlanamadı, daha net bir fotoğraf dener misiniz?');
      }
    } catch (err) {
      setFoodPhotoError(err.message || 'Fotoğraf analiz edilemedi.');
    } finally {
      setFoodPhotoAnalyzing(false);
    }
  };

  const confirmFoodPhoto = async () => {
    if (!foodPhotoPreview) return;
    try {
      await fetch(`${API_BASE}/api/nutrition/photo/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          meal_name: foodPhotoPreview.meal_name || 'Öğün',
          ingredients: foodPhotoPreview.description || '',
          calories: foodPhotoPreview.calories || 0,
          protein: foodPhotoPreview.protein || 0,
          carbs: foodPhotoPreview.carbs || 0,
          fats: foodPhotoPreview.fats || 0,
        }),
      });
      setFoodPhotoPreview(null);
      fetchDashboardData();
    } catch (e) {
      console.error(e);
      setFoodPhotoError('Kayıt sırasında hata oluştu.');
    }
  };

  const shiftSelectedDate = (deltaDays) => {
    const d = new Date(selectedDate);
    d.setDate(d.getDate() + deltaDays);
    setSelectedDate(d.toISOString().split('T')[0]);
  };

  const runWeeklyAnalysis = async () => {
    setAnalyzing(true);
    try {
      await fetch(`${API_BASE}/api/insights/generate`, { method: 'POST' });
      const res = await fetch(`${API_BASE}/api/insights`);
      setInsights(await res.json());
    } catch (e) {
      console.error(e);
    } finally {
      setAnalyzing(false);
    }
  };

  const submitWeight = async (e) => {
    e.preventDefault();
    if (!weightInput) return;
    setSavingWeight(true);
    try {
      await fetch(`${API_BASE}/api/metrics`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ weight: parseFloat(weightInput) }),
      });
      setWeightInput('');
      const res = await fetch(`${API_BASE}/api/metrics?days=30`);
      setMetrics(await res.json());
      fetchChartData();
    } catch (e) {
      console.error(e);
    } finally {
      setSavingWeight(false);
    }
  };

  const regenerateMealPlan = async () => {
    setGeneratingPlan(true);
    try {
      const res = await fetch(`${API_BASE}/api/mealplan/generate`, { method: 'POST' });
      setMealPlan(await res.json());
    } catch (e) {
      console.error(e);
    } finally {
      setGeneratingPlan(false);
    }
  };

  const deleteMealPlan = async () => {
    try {
      await fetch(`${API_BASE}/api/mealplan`, { method: 'DELETE' });
      setMealPlan([]);
    } catch (e) {
      console.error(e);
    }
  };

  const generateWorkoutProgram = async () => {
    setGeneratingProgram(true);
    try {
      const res = await fetch(`${API_BASE}/api/workout/program/generate`, { method: 'POST' });
      await res.json();
      const workoutRes = await fetch(`${API_BASE}/api/workout`);
      setWorkout(await workoutRes.json());
    } catch (e) {
      console.error(e);
    } finally {
      setGeneratingProgram(false);
    }
  };

  // Hedefler artık backend'deki profilden geliyor - sabit değil
  const targetCalories = profile?.daily_calorie_target || 2200;
  const targetProtein = profile?.daily_protein_target || 140;
  const targetCarbs = profile?.daily_carb_target || 220;

  const consumedCalories = nutritionPlans.reduce((acc, plan) => acc + (plan.calories || 0), 0);
  const consumedProtein = nutritionPlans.reduce((acc, plan) => acc + (plan.target_protein || 0), 0);
  const consumedCarbs = nutritionPlans.reduce((acc, plan) => acc + (plan.target_carbs || 0), 0);

  const caloriePercent = targetCalories > 0 ? (consumedCalories / targetCalories) : 0;
  const dashOffset = 2 * Math.PI * 50 - (Math.min(caloriePercent, 1)) * (2 * Math.PI * 50);

  const latestWeight = metrics.length > 0 ? metrics[metrics.length - 1].weight : profile?.current_weight;
  const firstWeight = metrics.find(m => m.weight)?.weight;
  const weightDelta = (latestWeight && firstWeight) ? (latestWeight - firstWeight) : null;

  const latestAnalysis = insights.find(i => i.category === 'analysis');

  if (loading) {
    return (
      <div className="min-h-screen bg-neutral-950 text-white flex items-center justify-center font-mono">
        🔄 AI.COACH_OS Veritabanı Bağlantısı Kuruluyor...
      </div>
    );
  }

  // ==========================================
  // KİLİTLİ EKRAN (VERİ YOKSA)
  // ==========================================
  if (!isSetupComplete) {
    return <OnboardingWizard onComplete={fetchDashboardData} />;
  }

  // ==========================================
  // CANLI DASHBOARD
  // ==========================================
  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 font-sans antialiased pb-12">
      <header className="border-b border-neutral-900 bg-neutral-900/50 backdrop-blur sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 py-4 flex justify-between items-center">
          <div className="flex items-center gap-3">
            <div className="h-3 w-3 bg-emerald-500 rounded-full animate-pulse"></div>
            <span className="font-mono font-black tracking-widest text-lg">AI.COACH_OS</span>
          </div>
          <nav className="flex bg-neutral-950 p-1 rounded-xl border border-neutral-800">
            {[
              ['flow', 'AKIŞ'],
              ['chat', 'JARVIS'],
              ['daily', 'GÜNLÜK'],
              ['workout', 'ANTRENMAN'],
              ['nutrition', 'MUTFAK'],
              ['progress', 'GELİŞİM'],
            ].map(([key, label]) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`px-4 py-2 rounded-lg text-xs font-mono transition-all ${activeTab === key ? 'bg-orange-500 text-black font-bold' : 'text-neutral-400 hover:text-white'}`}
              >
                {label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 mt-8 space-y-8">

        {activeTab === 'flow' && (
          <div className="space-y-6 animate-fadeIn">
            <div className="bg-gradient-to-r from-neutral-900 to-neutral-900/40 border border-neutral-800 p-6 rounded-2xl">
              <span className="text-xs font-mono bg-emerald-500/10 text-emerald-500 px-3 py-1 rounded-full border border-emerald-500/20">
                {profile?.goal ? `HEDEF: ${profile.goal.toUpperCase()}` : 'CANLI BAĞLANTI'}
              </span>
              <h2 className="text-2xl font-black mt-2">Sistem Canlı Veriye Bağlandı!</h2>
              <p className="text-neutral-400 text-sm mt-1">Telegram'dan veya Jarvis sekmesinden gönderdiğin her rapor 10 saniyede bir buraya otomatik yansıyacak.</p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <StatCard label="Kalori" value={`${consumedCalories.toFixed(0)} / ${targetCalories.toFixed(0)}`} accent="orange" />
              <StatCard label="Protein" value={`${consumedProtein.toFixed(0)}g / ${targetProtein.toFixed(0)}g`} accent="emerald" />
              <StatCard label="Güncel Kilo" value={latestWeight ? `${latestWeight} kg` : '—'} accent="orange" />
            </div>

            {latestAnalysis && (
              <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-2xl">
                <h3 className="font-mono text-xs uppercase tracking-wider text-neutral-400 mb-3">📊 Son Haftalık Analiz</h3>
                <p className="text-sm text-neutral-300 whitespace-pre-line leading-relaxed">{latestAnalysis.content}</p>
              </div>
            )}
          </div>
        )}

        {activeTab === 'chat' && (
          <JarvisChatPanel
            messages={chatMessages}
            input={chatInput}
            sending={chatSending}
            onInputChange={setChatInput}
            onSubmit={sendChatMessage}
            chatEndRef={chatEndRef}
          />
        )}

        {activeTab === 'daily' && (
          <div className="space-y-6 animate-fadeIn">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-xl font-black font-mono tracking-tight text-orange-500">// GÜNLÜK PENCERE</h2>
              <div className="flex items-center gap-2">
                <button onClick={() => shiftSelectedDate(-1)}
                  className="bg-neutral-900 border border-neutral-800 text-neutral-300 w-8 h-8 rounded-lg hover:bg-neutral-800">‹</button>
                <input
                  type="date" value={selectedDate} max={new Date().toISOString().split('T')[0]}
                  onChange={(e) => setSelectedDate(e.target.value)}
                  className="bg-neutral-900 border border-neutral-800 rounded-lg px-3 py-1.5 text-sm font-mono text-neutral-200 focus:outline-none focus:border-orange-500"
                />
                <button onClick={() => shiftSelectedDate(1)} disabled={selectedDate >= new Date().toISOString().split('T')[0]}
                  className="bg-neutral-900 border border-neutral-800 text-neutral-300 w-8 h-8 rounded-lg hover:bg-neutral-800 disabled:opacity-30">›</button>
              </div>
            </div>

            {loadingDaily ? (
              <p className="text-sm text-neutral-600 font-mono">Yükleniyor...</p>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-2xl space-y-4">
                  <h3 className="text-xs font-mono uppercase text-neutral-400 tracking-wider">🍽️ O Gün Yenenler</h3>
                  {dailyNutrition && dailyNutrition.meals && dailyNutrition.meals.length > 0 ? (
                    <>
                      <div className="flex gap-4 text-xs font-mono text-neutral-400">
                        <span>{dailyNutrition.summary.calories.toFixed(0)} kcal</span>
                        <span>{dailyNutrition.summary.protein.toFixed(0)}g protein</span>
                        <span>{dailyNutrition.summary.carbs.toFixed(0)}g karb</span>
                        <span>{dailyNutrition.summary.fats.toFixed(0)}g yağ</span>
                      </div>
                      <div className="space-y-2">
                        {dailyNutrition.meals.map((m) => (
                          <div key={m.id} className="p-3 bg-neutral-950 border border-neutral-800 rounded-xl">
                            <p className="text-sm font-bold">{m.meal_name}</p>
                            <p className="text-xs text-neutral-500">{m.ingredients}</p>
                            <span className="text-[10px] font-mono text-emerald-400">{m.calories.toFixed(0)} kcal | {m.protein.toFixed(0)}g P</span>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : (
                    <p className="text-sm text-neutral-600 font-mono">Bu gün için beslenme kaydı yok.</p>
                  )}
                </div>

                <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-2xl space-y-4">
                  <h3 className="text-xs font-mono uppercase text-neutral-400 tracking-wider">🏋️ O Gün Yapılan Antrenman</h3>
                  {dailyWorkout && dailyWorkout.logs && dailyWorkout.logs.length > 0 ? (
                    <>
                      <p className="text-xs font-mono text-neutral-400">{dailyWorkout.total_sets} set</p>
                      <div className="space-y-2">
                        {dailyWorkout.logs.map((l, i) => (
                          <div key={i} className="flex justify-between p-3 bg-neutral-950 border border-neutral-800 rounded-xl text-sm">
                            <span>{l.exercise_name} — Set {l.set_number}</span>
                            <span className="font-mono text-orange-400">{l.weight_lifted}kg x {l.reps_done}{l.rpe ? ` (RPE ${l.rpe})` : ''}</span>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : (
                    <p className="text-sm text-neutral-600 font-mono">Bu gün için antrenman kaydı yok.</p>
                  )}
                </div>
              </div>
            )}

            {!loadingDaily && Object.keys(dailyHeatmap).length > 0 && (
              <div className="bg-neutral-900 border border-neutral-800 p-5 rounded-2xl">
                <h3 className="text-xs font-mono uppercase text-neutral-400 tracking-wider mb-4">🔥 O Günün Kas Isı Haritası</h3>
                <MuscleHeatmap data={dailyHeatmap} />
              </div>
            )}
          </div>
        )}

        {activeTab === 'workout' && (
          <div className="space-y-6 animate-fadeIn">
            <h2 className="text-xl font-black font-mono tracking-tight text-orange-500">// GÜNÜN HİPERTROFİ REÇETESİ</h2>

            {deloadStatus && deloadStatus.needs_deload && (
              <div className="bg-orange-500/10 border border-orange-500/30 p-4 rounded-2xl">
                <p className="text-sm font-bold text-orange-400">⚠️ Deload Haftası Önerisi</p>
                <p className="text-xs text-neutral-400 mt-1">
                  Son antrenmanlarda durağanlık veya yüksek yorgunluk tespit edildi. Bu hafta
                  ağırlıkları %40-50 azaltıp toparlanmayı önceliklendirmeyi düşün.
                </p>
              </div>
            )}

            {(!workout.programs || workout.programs.length === 0) ? (
              <div className="p-8 bg-neutral-900 border border-neutral-800 border-dashed rounded-2xl text-center space-y-4">
                <p className="text-neutral-500 font-mono text-sm">
                  🏃‍♂️ Henüz aktif bir program yok.
                </p>
                <button onClick={generateWorkoutProgram} disabled={generatingProgram}
                  className="bg-orange-500 text-black text-xs font-bold px-5 py-2.5 rounded-lg disabled:opacity-50">
                  {generatingProgram ? 'OLUŞTURULUYOR...' : 'PROFİLİME GÖRE PROGRAM OLUŞTUR'}
                </button>
              </div>
            ) : (
              <div className="space-y-4">
                {workout.programs.map((program) => (
                  <div key={program.id} className="bg-neutral-900 border border-neutral-800 rounded-2xl p-6">
                    <h3 className="font-bold text-lg mb-4">{program.day_name}</h3>
                    <div className="space-y-2">
                      {program.exercises.map((ex) => (
                        <div key={ex.id} className="p-3 bg-neutral-950 border border-neutral-800 rounded-xl text-sm space-y-1">
                          <div className="flex justify-between items-center">
                            <span className="font-medium">{ex.name}</span>
                            <span className="font-mono text-xs text-neutral-400">{ex.target_sets} set x {ex.target_reps} tekrar</span>
                          </div>
                          {ex.progression && ex.progression.status !== 'no_data' && (
                            <p className={`text-xs font-mono ${PROGRESSION_COLOR[ex.progression.status] || 'text-neutral-500'}`}>
                              {PROGRESSION_ICON[ex.progression.status] || '•'} {ex.progression.message}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div>
              <h3 className="font-mono text-xs uppercase tracking-wider text-neutral-400 mb-3">Bugün Kaydedilen Setler</h3>
              {(!workout.today_logs || workout.today_logs.length === 0) ? (
                <p className="text-sm text-neutral-600 font-mono">Bugün henüz set girilmedi.</p>
              ) : (
                <div className="space-y-2">
                  {workout.today_logs.map((log, i) => (
                    <div key={i} className="flex justify-between p-3 bg-neutral-900 border border-neutral-800 rounded-xl text-sm">
                      <span>{log.exercise_name} — Set {log.set_number}</span>
                      <span className="font-mono text-emerald-400">{log.weight_lifted}kg x {log.reps_done}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'nutrition' && (
          <div className="space-y-6 animate-fadeIn">
            <h2 className="text-xl font-black font-mono tracking-tight text-emerald-500">// ANABOLİK MUTFAK VE MAKROLAR</h2>

            <FoodPhotoUpload
              preview={foodPhotoPreview}
              analyzing={foodPhotoAnalyzing}
              error={foodPhotoError}
              inputRef={foodPhotoInputRef}
              onFileSelect={analyzeFoodPhoto}
              onConfirm={confirmFoodPhoto}
              onCancel={() => { setFoodPhotoPreview(null); setFoodPhotoError(''); }}
            />

            <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-2xl space-y-4">
              <div className="flex justify-between items-center">
                <h3 className="text-xs font-mono uppercase text-neutral-400 tracking-wider">📋 Jarvis'in Önerdiği Plan (Henüz Yenmedi)</h3>
                <div className="flex gap-2">
                  {mealPlan.length > 0 && (
                    <button onClick={deleteMealPlan}
                      className="bg-neutral-800 text-neutral-300 text-xs font-bold px-4 py-2 rounded-lg hover:bg-neutral-700">
                      KALDIR
                    </button>
                  )}
                  <button onClick={regenerateMealPlan} disabled={generatingPlan}
                    className="bg-emerald-500 text-black text-xs font-bold px-4 py-2 rounded-lg disabled:opacity-50">
                    {generatingPlan ? 'OLUŞTURULUYOR...' : 'YENİ PLAN OLUŞTUR'}
                  </button>
                </div>
              </div>
              {mealPlan.length === 0 ? (
                <p className="text-sm text-neutral-600 font-mono">Henüz bir plan yok. Telegram'da /beslenme yaz veya yukarıdaki butona bas.</p>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {mealPlan.map((item) => (
                    <div key={item.id} className="p-4 bg-neutral-950 border border-neutral-800 rounded-xl">
                      <div className="flex justify-between items-baseline">
                        <h4 className="text-sm font-bold text-white">{item.meal_name}</h4>
                        <span className="text-[10px] font-mono text-neutral-500">{item.time_target}</span>
                      </div>
                      <p className="text-xs text-neutral-400 mt-1">{item.description}</p>
                      <span className="text-[10px] font-mono text-emerald-400 block mt-2">
                        {item.calories.toFixed(0)} kcal | P:{item.protein.toFixed(0)}g | K:{item.carbs.toFixed(0)}g | Y:{item.fats.toFixed(0)}g
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">

              <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-2xl flex flex-col justify-between">
                <div>
                  <h3 className="text-xs font-mono uppercase text-neutral-400 tracking-wider mb-6 text-center">Bugünkü İlerleme</h3>
                  <div className="relative flex items-center justify-center my-4">
                    <svg className="w-40 h-40 transform -rotate-90">
                      <circle cx="80" cy="80" r="50" className="text-neutral-800" strokeWidth="10" fill="transparent" />
                      <circle cx="80" cy="80" r="50" className="text-emerald-500 transition-all duration-500" strokeWidth="10" strokeDasharray={2 * Math.PI * 50} strokeDashoffset={dashOffset} strokeLinecap="round" fill="transparent" />
                    </svg>
                    <div className="absolute text-center">
                      <span className="text-2xl font-black block">{consumedCalories.toFixed(0)}</span>
                      <span className="text-[10px] font-mono text-neutral-500 uppercase">/ {targetCalories.toFixed(0)} kcal</span>
                    </div>
                  </div>
                </div>
                <div className="space-y-3 mt-6 font-mono text-xs">
                  <MacroBar label="PROTEİN" value={consumedProtein} target={targetProtein} color="bg-emerald-500" />
                  <MacroBar label="KARBONHİDRAT" value={consumedCarbs} target={targetCarbs} color="bg-orange-500" />
                </div>
              </div>

              <div className="lg:col-span-2 space-y-4">
                <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-2xl space-y-4">
                  <h3 className="font-mono text-xs uppercase tracking-wider text-neutral-400">✅ Bugün Gerçekten Yediklerin (Kayıt)</h3>
                  {nutritionPlans.length === 0 ? (
                    <p className="text-sm text-neutral-600 font-mono">Bugün henüz öğün girilmedi.</p>
                  ) : (
                    <div className="space-y-3">
                      {nutritionPlans.map((plan) => (
                        <div key={plan.id} className="flex justify-between items-center p-4 bg-neutral-950 border border-neutral-800 rounded-xl">
                          <div>
                            <h4 className="text-sm font-bold text-white">{plan.meal_name} {plan.time_target ? `(${plan.time_target})` : ''}</h4>
                            <p className="text-xs text-neutral-500 font-mono">{plan.ingredients}</p>
                            <span className="text-[10px] font-mono text-emerald-400">P: {plan.target_protein}g | K: {plan.target_carbs}g | Kalori: {plan.calories} kcal</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

            </div>
          </div>
        )}

        {activeTab === 'progress' && (
          <div className="space-y-6 animate-fadeIn">
            <h2 className="text-xl font-black font-mono tracking-tight text-orange-500">// GELİŞİM VE ANALİZ</h2>

            <ProgressChartsSection
              chartData={chartData}
              loading={loadingCharts}
              metrics={metrics}
              weightDelta={weightDelta}
              weightInput={weightInput}
              savingWeight={savingWeight}
              onWeightInputChange={setWeightInput}
              onSubmitWeight={submitWeight}
            />

            <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-2xl space-y-4">
              <div className="flex justify-between items-center">
                <h3 className="text-xs font-mono uppercase text-neutral-400 tracking-wider">Jarvis'in Analizleri</h3>
                <button onClick={runWeeklyAnalysis} disabled={analyzing}
                  className="bg-emerald-500 text-black text-xs font-bold px-4 py-2 rounded-lg disabled:opacity-50">
                  {analyzing ? 'ANALİZ EDİLİYOR...' : 'ŞİMDİ ANALİZ ET'}
                </button>
              </div>
              {insights.length === 0 ? (
                <p className="text-sm text-neutral-600 font-mono">Henüz kayıtlı içgörü yok. Bir hafta veri girdikten sonra "Şimdi Analiz Et" butonuna bas.</p>
              ) : (
                <div className="space-y-3 max-h-96 overflow-y-auto pr-2">
                  {insights.map((ins) => (
                    <div key={ins.id} className="p-4 bg-neutral-950 border border-neutral-800 rounded-xl">
                      <span className="text-[10px] font-mono uppercase text-orange-400">{ins.category}</span>
                      <p className="text-sm text-neutral-300 mt-1 whitespace-pre-line">{ins.content}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

      </main>
    </div>
  );
}

function StatCard({ label, value, accent }) {
  const color = accent === 'orange' ? 'text-orange-500' : 'text-emerald-500';
  return (
    <div className="bg-neutral-900 border border-neutral-800 p-5 rounded-2xl">
      <p className="text-[10px] font-mono uppercase text-neutral-500 tracking-wider">{label}</p>
      <p className={`text-xl font-black font-mono mt-1 ${color}`}>{value}</p>
    </div>
  );
}

function MacroBar({ label, value, target, color }) {
  return (
    <div>
      <div className="flex justify-between mb-1"><span>{label}</span><span className="font-bold text-neutral-300">{value.toFixed(0)}g / {target.toFixed(0)}g</span></div>
      <div className="w-full bg-neutral-950 h-2 rounded-full overflow-hidden">
        <div className={`${color} h-full`} style={{ width: `${Math.min((value / target) * 100, 100)}%` }}></div>
      </div>
    </div>
  );
}

function WeightSparkline({ metrics }) {
  const points = metrics.filter(m => m.weight).map(m => m.weight);
  if (points.length < 2) {
    return <p className="text-2xl font-black font-mono text-white">{points[0]} kg</p>;
  }
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const w = 240, h = 60, pad = 4;
  const step = (w - pad * 2) / (points.length - 1);
  const path = points.map((p, i) => {
    const x = pad + i * step;
    const y = h - pad - ((p - min) / range) * (h - pad * 2);
    return `${i === 0 ? 'M' : 'L'}${x},${y}`;
  }).join(' ');

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-16">
      <path d={path} fill="none" stroke="#f97316" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const CHART_TOOLTIP_STYLE = {
  contentStyle: { background: '#171717', border: '1px solid #404040', borderRadius: '8px', fontSize: '11px' },
  labelStyle: { color: '#a3a3a3' },
};

function JarvisChatPanel({ messages, input, sending, onInputChange, onSubmit, chatEndRef }) {
  return (
    <div className="space-y-4 animate-fadeIn max-w-3xl mx-auto">
      <div className="bg-neutral-900 border border-neutral-800 rounded-2xl flex flex-col h-[calc(100vh-220px)] min-h-[420px]">
        <div className="px-5 py-4 border-b border-neutral-800 flex items-center gap-3">
          <span className="text-2xl">🤖</span>
          <div>
            <h2 className="font-black text-sm tracking-wide">JARVIS</h2>
            <p className="text-[10px] font-mono text-neutral-500">Beslenme · Antrenman · Hedefler</p>
          </div>
          <span className="ml-auto text-[10px] font-mono text-emerald-500 bg-emerald-500/10 px-2 py-1 rounded-full border border-emerald-500/20">CANLI</span>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] px-4 py-3 rounded-2xl text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-orange-500 text-black font-medium rounded-br-md'
                  : 'bg-neutral-950 border border-neutral-800 text-neutral-200 rounded-bl-md'
              }`}>
                {msg.text}
                {msg.intent && msg.intent !== 'chat' && (
                  <span className="block mt-1.5 text-[9px] font-mono opacity-60 uppercase">{msg.intent.replace(/_/g, ' ')}</span>
                )}
              </div>
            </div>
          ))}
          {sending && (
            <div className="flex justify-start">
              <div className="bg-neutral-950 border border-neutral-800 px-4 py-3 rounded-2xl rounded-bl-md text-sm text-neutral-500 font-mono animate-pulse">
                Jarvis düşünüyor...
              </div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        <form onSubmit={onSubmit} className="p-4 border-t border-neutral-800 flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => onInputChange(e.target.value)}
            placeholder="Örn: 3 yumurta yedim, bench 80kg x 8..."
            disabled={sending}
            className="flex-1 bg-neutral-950 border border-neutral-800 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-orange-500 disabled:opacity-50"
          />
          <button type="submit" disabled={sending || !input.trim()}
            className="bg-orange-500 text-black font-bold px-5 py-3 rounded-xl text-sm disabled:opacity-40">
            GÖNDER
          </button>
        </form>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[10px] font-mono text-neutral-600">
        {['3 yumurta yedim', 'bench 80kg x 8', 'kilo 78.5', 'dün ne yedim?'].map((hint) => (
          <button key={hint} type="button" onClick={() => onInputChange(hint)}
            className="bg-neutral-900 border border-neutral-800 rounded-lg px-2 py-2 hover:border-neutral-600 hover:text-neutral-400 transition-colors text-left truncate">
            {hint}
          </button>
        ))}
      </div>
    </div>
  );
}

function FoodPhotoUpload({ preview, analyzing, error, inputRef, onFileSelect, onConfirm, onCancel }) {
  return (
    <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-2xl space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="text-xs font-mono uppercase text-neutral-400 tracking-wider">📸 Tabak Fotoğrafı ile Kaydet</h3>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="hidden"
          onChange={(e) => { if (e.target.files?.[0]) onFileSelect(e.target.files[0]); e.target.value = ''; }}
        />
        {!preview && (
          <button
            onClick={() => inputRef.current?.click()}
            disabled={analyzing}
            className="bg-emerald-500 text-black text-xs font-bold px-4 py-2 rounded-lg disabled:opacity-50"
          >
            {analyzing ? 'ANALİZ EDİLİYOR...' : 'FOTOĞRAF YÜKLE'}
          </button>
        )}
      </div>

      {error && <p className="text-xs text-red-400">{error}</p>}

      {preview && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <img src={preview.previewUrl} alt="Yemek" className="rounded-xl border border-neutral-800 w-full max-h-48 object-cover" />
          <div className="space-y-3">
            <div>
              <p className="font-bold text-white">{preview.meal_name}</p>
              <p className="text-xs text-neutral-400 mt-1">{preview.description}</p>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs font-mono">
              <span className="bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2">{preview.calories?.toFixed(0)} kcal</span>
              <span className="bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2">{preview.protein?.toFixed(0)}g protein</span>
              <span className="bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2">{preview.carbs?.toFixed(0)}g karb</span>
              <span className="bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2">{preview.fats?.toFixed(0)}g yağ</span>
            </div>
            {preview.confidence === 'low' && (
              <p className="text-[10px] text-orange-400 font-mono">⚠️ Düşük güven — makroları kontrol edin</p>
            )}
            <div className="flex gap-2">
              <button onClick={onCancel} className="flex-1 bg-neutral-800 text-white text-xs font-bold py-2.5 rounded-lg">İPTAL</button>
              <button onClick={onConfirm} className="flex-1 bg-emerald-500 text-black text-xs font-bold py-2.5 rounded-lg">KAYDET</button>
            </div>
          </div>
        </div>
      )}

      {!preview && !analyzing && (
        <p className="text-xs text-neutral-600 font-mono">Tabak fotoğrafını yükle — AI makroları hesaplasın, sen onayla.</p>
      )}
    </div>
  );
}

function ProgressChartsSection({ chartData, loading, metrics, weightDelta, weightInput, savingWeight, onWeightInputChange, onSubmitWeight }) {
  const formatDate = (d) => {
    if (!d) return '';
    const parts = d.split('-');
    return parts.length >= 3 ? `${parts[2]}/${parts[1]}` : d;
  };

  const nutritionChart = chartData?.nutrition?.map((d) => ({
    ...d,
    label: formatDate(d.date),
    calTarget: chartData?.targets?.calories || 0,
    protTarget: chartData?.targets?.protein || 0,
  })) || [];

  const weightChart = chartData?.weight?.map((d) => ({
    ...d,
    label: formatDate(d.date),
  })) || [];

  const volumeChart = chartData?.volume || [];

  if (loading) {
    return <p className="text-sm text-neutral-600 font-mono">Grafikler yükleniyor...</p>;
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Kilo trendi */}
      <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-2xl space-y-4">
        <h3 className="text-xs font-mono uppercase text-neutral-400 tracking-wider">Kilo Trendi (14 gün)</h3>
        {weightChart.length === 0 ? (
          <p className="text-sm text-neutral-600 font-mono">Henüz kilo kaydı yok.</p>
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={weightChart}>
              <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
              <XAxis dataKey="label" tick={{ fill: '#737373', fontSize: 10 }} />
              <YAxis domain={['auto', 'auto']} tick={{ fill: '#737373', fontSize: 10 }} width={35} />
              <Tooltip contentStyle={CHART_TOOLTIP_STYLE.contentStyle} formatter={(v) => [`${v} kg`, 'Kilo']} />
              <Line type="monotone" dataKey="weight" stroke="#f97316" strokeWidth={2} dot={{ fill: '#f97316', r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        )}
        {weightDelta !== null && (
          <p className="text-xs font-mono text-neutral-400">
            Dönem değişimi: <span className={weightDelta <= 0 ? 'text-emerald-400' : 'text-orange-400'}>{weightDelta > 0 ? '+' : ''}{weightDelta.toFixed(1)} kg</span>
          </p>
        )}
        <form onSubmit={onSubmitWeight} className="flex gap-2 pt-2">
          <input type="number" step="0.1" placeholder="kg" value={weightInput}
            onChange={(e) => onWeightInputChange(e.target.value)}
            className="flex-1 bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-orange-500" />
          <button type="submit" disabled={savingWeight}
            className="bg-orange-500 text-black text-xs font-bold px-4 py-2 rounded-lg disabled:opacity-50">
            {savingWeight ? '...' : 'KAYDET'}
          </button>
        </form>
      </div>

      {/* Makro uyumu */}
      <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-2xl space-y-4">
        <h3 className="text-xs font-mono uppercase text-neutral-400 tracking-wider">Günlük Kalori (Plan vs Gerçek)</h3>
        {nutritionChart.length === 0 ? (
          <p className="text-sm text-neutral-600 font-mono">Beslenme verisi yok.</p>
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={nutritionChart}>
              <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
              <XAxis dataKey="label" tick={{ fill: '#737373', fontSize: 10 }} />
              <YAxis tick={{ fill: '#737373', fontSize: 10 }} width={40} />
              <Tooltip contentStyle={CHART_TOOLTIP_STYLE.contentStyle} />
              <ReferenceLine y={chartData?.targets?.calories} stroke="#10b981" strokeDasharray="4 4" label={{ value: 'Hedef', fill: '#10b981', fontSize: 10 }} />
              <Bar dataKey="calories" fill="#f97316" radius={[4, 4, 0, 0]} name="Kalori" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Protein trendi */}
      <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-2xl space-y-4">
        <h3 className="text-xs font-mono uppercase text-neutral-400 tracking-wider">Günlük Protein</h3>
        {nutritionChart.length === 0 ? (
          <p className="text-sm text-neutral-600 font-mono">Protein verisi yok.</p>
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={nutritionChart}>
              <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
              <XAxis dataKey="label" tick={{ fill: '#737373', fontSize: 10 }} />
              <YAxis tick={{ fill: '#737373', fontSize: 10 }} width={40} />
              <Tooltip contentStyle={CHART_TOOLTIP_STYLE.contentStyle} formatter={(v) => [`${v}g`, 'Protein']} />
              <ReferenceLine y={chartData?.targets?.protein} stroke="#10b981" strokeDasharray="4 4" />
              <Bar dataKey="protein" fill="#10b981" radius={[4, 4, 0, 0]} name="Protein (g)" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Kas hacmi */}
      <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-2xl space-y-4">
        <h3 className="text-xs font-mono uppercase text-neutral-400 tracking-wider">Haftalık Kas Grubu Hacmi (Set)</h3>
        {volumeChart.length === 0 ? (
          <p className="text-sm text-neutral-600 font-mono">Antrenman verisi yok.</p>
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={volumeChart} layout="vertical" margin={{ left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#262626" horizontal={false} />
              <XAxis type="number" tick={{ fill: '#737373', fontSize: 10 }} />
              <YAxis type="category" dataKey="muscle_group" tick={{ fill: '#a3a3a3', fontSize: 10 }} width={60} />
              <Tooltip contentStyle={CHART_TOOLTIP_STYLE.contentStyle} formatter={(v) => [`${v} set`, 'Hacim']} />
              <Bar dataKey="sets" fill="#ea580c" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

// Set sayısına göre ısı rengi belirler. Eşikler haftalık hipertrofi hacim standartlarına
// yaklaşık dayanır (haftada ~10-20 set/kas grubu optimal aralık kabul edilir).
function getHeatColor(sets) {
  if (!sets || sets === 0) return '#3f3f46';        // neutral-700 - hiç çalışılmamış (nötr gri gövde)
  if (sets <= 4) return '#a16207';                   // amber-700 - düşük
  if (sets <= 8) return '#f97316';                   // orange-500 - orta
  if (sets <= 14) return '#ea580c';                  // orange-600 - yüksek
  return '#dc2626';                                  // red-600 - çok yüksek
}

// getHeatColor ile aynı eşiklere göre, o yoğunluk kovasının <defs> içinde tanımlı
// gradyanına referans döner - düz renk yerine "dolgun/parlak kas" hissi veren
// hafif 3D degradeler için kullanılır.
function getHeatGradientId(sets) {
  if (!sets || sets === 0) return 'heatNone';
  if (sets <= 4) return 'heatLow';
  if (sets <= 8) return 'heatMed';
  if (sets <= 14) return 'heatHigh';
  return 'heatMax';
}

// Referans anatomi görseline benzer, profesyonel/anatomik ÖN ve ARKA gövdeyi yan yana
// gösteren ısı haritası. Nötr, gölgeli-gri bir vücut siluetinin üzerine, o gün çalışılan
// kas gruplarını degrade renkle ve hafif "glow" ile vurguluyor - çalışılmayan kaslar
// gri anatomik detayında kalırken, çalışılanlar referans fotoğraftaki gibi öne çıkıyor.
// Kol ve Bacak hem ön (biceps/quad) hem arka (triceps/hamstring-glute) görünümde aynı
// renkte çıkar çünkü veri modelimizde bu ayrım yok, tek "Kol"/"Bacak" kategorisi var.
function MuscleHeatmap({ data }) {
  const sets = (group) => (data[group]?.sets) || 0;
  const fillFor = (group) => `url(#${getHeatGradientId(sets(group))})`;
  const glowFor = (group) => (sets(group) > 0 ? 'url(#muscleGlow)' : undefined);
  const neutral = 'url(#neutralGrad)'; // el, ayak, kafa gibi takip edilmeyen bölgeler
  const seam = 'rgba(0,0,0,0.35)'; // kas ayrım/tanım çizgileri

  const legendGroups = ['Göğüs', 'Sırt', 'Omuz', 'Kol', 'Karın', 'Bacak'];

  return (
    <div className="flex flex-col md:flex-row items-center gap-6">
      <svg viewBox="0 0 480 400" className="w-full max-w-lg h-auto shrink-0">
        <defs>
          <radialGradient id="neutralGrad" cx="35%" cy="30%" r="75%">
            <stop offset="0%" stopColor="#52525b" />
            <stop offset="100%" stopColor="#26262a" />
          </radialGradient>
          <radialGradient id="heatNone" cx="35%" cy="30%" r="75%">
            <stop offset="0%" stopColor="#52525b" />
            <stop offset="100%" stopColor="#303035" />
          </radialGradient>
          <radialGradient id="heatLow" cx="35%" cy="30%" r="75%">
            <stop offset="0%" stopColor="#d97706" />
            <stop offset="100%" stopColor="#78350f" />
          </radialGradient>
          <radialGradient id="heatMed" cx="35%" cy="30%" r="75%">
            <stop offset="0%" stopColor="#fdba74" />
            <stop offset="100%" stopColor="#ea580c" />
          </radialGradient>
          <radialGradient id="heatHigh" cx="35%" cy="30%" r="75%">
            <stop offset="0%" stopColor="#fb923c" />
            <stop offset="100%" stopColor="#c2410c" />
          </radialGradient>
          <radialGradient id="heatMax" cx="35%" cy="30%" r="75%">
            <stop offset="0%" stopColor="#f87171" />
            <stop offset="100%" stopColor="#b91c1c" />
          </radialGradient>
          <filter id="muscleGlow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="3.2" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* ========== ÖN GÖRÜNÜM ========== */}
        <g>
          <text x="95" y="14" textAnchor="middle" className="fill-neutral-500" style={{ font: '9px monospace', letterSpacing: '1px' }}>ÖN</text>
          {/* Kafa + boyun */}
          <ellipse cx="95" cy="34" rx="14" ry="17" fill={neutral} />
          <path d="M85,48 L105,48 L102,64 L88,64 Z" fill={neutral} />
          {/* Trapez (Sırt - önden az görünen kısım) */}
          <path d="M66,66 C78,58 95,54 95,54 C95,54 112,58 124,66 L113,76 C104,70 95,68 95,68 C95,68 86,70 77,76 Z" fill={fillFor('Sırt')} filter={glowFor('Sırt')} stroke={seam} strokeWidth="0.6" />
          {/* Omuzlar (anterior deltoid) */}
          <path d="M66,68 C50,68 40,80 40,96 C40,108 48,116 58,114 C66,112 70,98 70,86 C70,78 69,72 66,68 Z" fill={fillFor('Omuz')} filter={glowFor('Omuz')} stroke={seam} strokeWidth="0.6" />
          <path d="M124,68 C140,68 150,80 150,96 C150,108 142,116 132,114 C124,112 120,98 120,86 C120,78 121,72 124,68 Z" fill={fillFor('Omuz')} filter={glowFor('Omuz')} stroke={seam} strokeWidth="0.6" />
          <path d="M52,84 C55,90 56,98 55,106" fill="none" stroke={seam} strokeWidth="0.6" opacity="0.5" />
          <path d="M138,84 C135,90 134,98 135,106" fill="none" stroke={seam} strokeWidth="0.6" opacity="0.5" />
          {/* Göğüs (pektoral - üst/alt ayrımlı, ortada sternum çizgisi) */}
          <path d="M95,66 C82,62 68,66 63,80 C59,94 63,110 78,116 C88,120 94,114 95,104 Z" fill={fillFor('Göğüs')} filter={glowFor('Göğüs')} stroke={seam} strokeWidth="0.6" />
          <path d="M95,66 C108,62 122,66 127,80 C131,94 127,110 112,116 C102,120 96,114 95,104 Z" fill={fillFor('Göğüs')} filter={glowFor('Göğüs')} stroke={seam} strokeWidth="0.6" />
          <path d="M95,66 L95,116" fill="none" stroke={seam} strokeWidth="1" opacity="0.6" />
          <path d="M68,88 C76,92 84,94 93,94" fill="none" stroke={seam} strokeWidth="0.5" opacity="0.35" />
          <path d="M122,88 C114,92 106,94 97,94" fill="none" stroke={seam} strokeWidth="0.5" opacity="0.35" />
          {/* Serratus anterior - kaburga altı çizgiler (dekoratif, nötr) */}
          <path d="M64,102 L72,108 M62,110 L71,115 M120,110 L129,115 M118,102 L126,108" fill="none" stroke={seam} strokeWidth="0.5" opacity="0.3" />
          {/* Kollar (biceps) */}
          <path d="M48,92 C36,98 32,112 34,132 C35,146 39,158 46,160 C52,162 56,156 55,144 C54,130 52,116 52,104 C52,98 51,94 48,92 Z" fill={fillFor('Kol')} filter={glowFor('Kol')} stroke={seam} strokeWidth="0.6" />
          <path d="M142,92 C154,98 158,112 156,132 C155,146 151,158 144,160 C138,162 134,156 135,144 C136,130 138,116 138,104 C138,98 139,94 142,92 Z" fill={fillFor('Kol')} filter={glowFor('Kol')} stroke={seam} strokeWidth="0.6" />
          {/* Ön kollar */}
          <path d="M38,158 C36,172 37,188 42,200 C45,206 52,206 53,198 C55,184 54,170 51,158 Z" fill={fillFor('Kol')} filter={glowFor('Kol')} stroke={seam} strokeWidth="0.5" />
          <path d="M152,158 C154,172 153,188 148,200 C145,206 138,206 137,198 C135,184 136,170 139,158 Z" fill={fillFor('Kol')} filter={glowFor('Kol')} stroke={seam} strokeWidth="0.5" />
          {/* Karın (6 parçalı, üstten alta daralan) + obliques */}
          <path d="M62,96 C58,110 58,126 62,140 C66,152 74,158 80,158 L80,96 Z" fill={fillFor('Karın')} filter={glowFor('Karın')} stroke={seam} strokeWidth="0.5" opacity="0.9" />
          <path d="M128,96 C132,110 132,126 128,140 C124,152 116,158 110,158 L110,96 Z" fill={fillFor('Karın')} filter={glowFor('Karın')} stroke={seam} strokeWidth="0.5" opacity="0.9" />
          {[0, 1, 2].map((row) => (
            <g key={row}>
              <rect x={81} y={98 + row * 18} width={row === 2 ? 12 : 13} height={row === 2 ? 15 : 16} rx="3" fill={fillFor('Karın')} filter={glowFor('Karın')} stroke={seam} strokeWidth="0.5" />
              <rect x={96 - (row === 2 ? 1 : 0)} y={98 + row * 18} width={row === 2 ? 12 : 13} height={row === 2 ? 15 : 16} rx="3" fill={fillFor('Karın')} filter={glowFor('Karın')} stroke={seam} strokeWidth="0.5" />
            </g>
          ))}
          <path d="M95,96 L95,158" fill="none" stroke={seam} strokeWidth="0.8" opacity="0.5" />
          {/* Kalça/hip taper */}
          <path d="M65,158 C62,166 63,172 68,176 L122,176 C127,172 128,166 125,158 Z" fill={neutral} />
          {/* Bacaklar (quad - iç/dış ayrımlı) */}
          <path d="M80,178 C70,192 66,220 68,252 C69,270 74,282 82,283 C88,284 90,272 89,254 C88,234 90,214 88,196 C87,188 84,182 80,178 Z" fill={fillFor('Bacak')} filter={glowFor('Bacak')} stroke={seam} strokeWidth="0.6" />
          <path d="M110,178 C120,192 124,220 122,252 C121,270 116,282 108,283 C102,284 100,272 101,254 C102,234 100,214 102,196 C103,188 106,182 110,178 Z" fill={fillFor('Bacak')} filter={glowFor('Bacak')} stroke={seam} strokeWidth="0.6" />
          <path d="M85,190 C83,212 83,236 85,258" fill="none" stroke={seam} strokeWidth="0.5" opacity="0.4" />
          <path d="M105,190 C107,212 107,236 105,258" fill="none" stroke={seam} strokeWidth="0.5" opacity="0.4" />
          {/* Alt bacak (kalf - nötr) */}
          <path d="M71,286 C68,302 68,320 72,336 C74,344 82,344 84,336 C87,320 87,302 85,286 Z" fill={neutral} />
          <path d="M109,286 C112,302 112,320 108,336 C106,344 98,344 96,336 C93,320 93,302 95,286 Z" fill={neutral} />
          {/* Ayaklar */}
          <ellipse cx="77" cy="350" rx="9" ry="6" fill={neutral} />
          <ellipse cx="103" cy="350" rx="9" ry="6" fill={neutral} />
        </g>

        {/* ========== ARKA GÖRÜNÜM ========== */}
        <g transform="translate(260, 0)">
          <text x="95" y="14" textAnchor="middle" className="fill-neutral-500" style={{ font: '9px monospace', letterSpacing: '1px' }}>ARKA</text>
          <ellipse cx="95" cy="34" rx="14" ry="17" fill={neutral} />
          <path d="M85,48 L105,48 L102,64 L88,64 Z" fill={neutral} />
          {/* Trapez (büyük kite şekli, boyundan belin ortasına) */}
          <path d="M95,52 L124,66 L136,96 L95,116 L54,96 L66,66 Z" fill={fillFor('Sırt')} filter={glowFor('Sırt')} stroke={seam} strokeWidth="0.6" />
          {/* Arka omuz (posterior deltoid) */}
          <path d="M66,68 C50,68 40,80 40,96 C40,108 48,116 58,114 C66,112 70,98 70,86 C70,78 69,72 66,68 Z" fill={fillFor('Omuz')} filter={glowFor('Omuz')} stroke={seam} strokeWidth="0.6" />
          <path d="M124,68 C140,68 150,80 150,96 C150,108 142,116 132,114 C124,112 120,98 120,86 C120,78 121,72 124,68 Z" fill={fillFor('Omuz')} filter={glowFor('Omuz')} stroke={seam} strokeWidth="0.6" />
          {/* Lats (kanat şeklinde geniş sırt kası) */}
          <path d="M70,98 C56,106 50,128 58,152 C64,168 80,176 92,168 L92,116 Z" fill={fillFor('Sırt')} filter={glowFor('Sırt')} stroke={seam} strokeWidth="0.6" />
          <path d="M120,98 C134,106 140,128 132,152 C126,168 110,176 98,168 L98,116 Z" fill={fillFor('Sırt')} filter={glowFor('Sırt')} stroke={seam} strokeWidth="0.6" />
          {/* Erector spinae - omurga boyunca ince şeritler */}
          <path d="M91,112 C89,130 89,150 91,168" fill="none" stroke={seam} strokeWidth="1" opacity="0.5" />
          <path d="M99,112 C101,130 101,150 99,168" fill="none" stroke={seam} strokeWidth="1" opacity="0.5" />
          {/* Triceps */}
          <path d="M48,92 C36,98 32,112 34,132 C35,146 39,158 46,160 C52,162 56,156 55,144 C54,130 52,116 52,104 C52,98 51,94 48,92 Z" fill={fillFor('Kol')} filter={glowFor('Kol')} stroke={seam} strokeWidth="0.6" />
          <path d="M142,92 C154,98 158,112 156,132 C155,146 151,158 144,160 C138,162 134,156 135,144 C136,130 138,116 138,104 C138,98 139,94 142,92 Z" fill={fillFor('Kol')} filter={glowFor('Kol')} stroke={seam} strokeWidth="0.6" />
          <path d="M42,108 C46,118 47,130 45,142" fill="none" stroke={seam} strokeWidth="0.5" opacity="0.4" />
          <path d="M148,108 C144,118 143,130 145,142" fill="none" stroke={seam} strokeWidth="0.5" opacity="0.4" />
          {/* Ön kollar */}
          <path d="M38,158 C36,172 37,188 42,200 C45,206 52,206 53,198 C55,184 54,170 51,158 Z" fill={fillFor('Kol')} filter={glowFor('Kol')} stroke={seam} strokeWidth="0.5" />
          <path d="M152,158 C154,172 153,188 148,200 C145,206 138,206 137,198 C135,184 136,170 139,158 Z" fill={fillFor('Kol')} filter={glowFor('Kol')} stroke={seam} strokeWidth="0.5" />
          {/* Bel - alt sırt (lumbar) */}
          <path d="M83,168 L107,168 L103,182 L87,182 Z" fill={fillFor('Sırt')} filter={glowFor('Sırt')} stroke={seam} strokeWidth="0.5" />
          {/* Kalça (glute) - orta hat çizgili */}
          <path d="M67,182 C58,188 56,204 62,216 C68,226 88,228 93,216 C96,208 94,192 88,182 Z" fill={fillFor('Bacak')} filter={glowFor('Bacak')} stroke={seam} strokeWidth="0.6" />
          <path d="M123,182 C132,188 134,204 128,216 C122,226 102,228 97,216 C94,208 96,192 102,182 Z" fill={fillFor('Bacak')} filter={glowFor('Bacak')} stroke={seam} strokeWidth="0.6" />
          <path d="M95,182 L95,222" fill="none" stroke={seam} strokeWidth="0.7" opacity="0.45" />
          {/* Hamstring (bacak arkası - iç/dış ayrımlı) */}
          <path d="M65,222 C60,242 60,262 65,280 C68,290 76,290 78,280 C81,262 80,242 76,224 Z" fill={fillFor('Bacak')} filter={glowFor('Bacak')} stroke={seam} strokeWidth="0.5" />
          <path d="M125,222 C130,242 130,262 125,280 C122,290 114,290 112,280 C109,262 110,242 114,224 Z" fill={fillFor('Bacak')} filter={glowFor('Bacak')} stroke={seam} strokeWidth="0.5" />
          <path d="M87,224 C89,244 89,262 87,278" fill="none" stroke={seam} strokeWidth="0.5" opacity="0.35" />
          <path d="M103,224 C101,244 101,262 103,278" fill="none" stroke={seam} strokeWidth="0.5" opacity="0.35" />
          {/* Kalf (nötr, ikiye ayrık gastrocnemius görünümü) */}
          <path d="M67,286 C63,302 64,320 70,336 C73,343 82,343 83,335 C85,320 84,302 80,286 Z" fill={neutral} />
          <path d="M113,286 C117,302 116,320 110,336 C107,343 98,343 97,335 C95,320 96,302 100,286 Z" fill={neutral} />
          <ellipse cx="77" cy="350" rx="9" ry="6" fill={neutral} />
          <ellipse cx="103" cy="350" rx="9" ry="6" fill={neutral} />
        </g>
      </svg>

      <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs font-mono w-full md:w-52 shrink-0">
        {legendGroups.map((group) => (
          <div key={group} className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-sm shrink-0 ring-1 ring-white/10" style={{ backgroundColor: getHeatColor(sets(group)) }}></span>
            <span className="text-neutral-400">{group}</span>
            <span className="text-neutral-300 ml-auto">{sets(group)}</span>
          </div>
        ))}
        <div className="col-span-2 mt-2 pt-2 border-t border-neutral-800 text-[10px] text-neutral-600 leading-relaxed">
          Renk yoğunluğu haftalık set hacmine göre değişir: gri (çalışılmadı) → sarı → turuncu → kırmızı (çok yüksek hacim).
        </div>
      </div>
    </div>
  );
}

// ==========================================
// ONBOARDING WIZARD — Profil oluşturma akışı.
// Kullanıcıdan önce temel bilgileri alır, sonra iyi ışıkta bir VÜCUT VİDEOSU ve
// güncel beslenme/antrenman/günlük rutinini anlattığı bir SESLİ KAYIT ister.
// İkisi de backend'de Gemini ile analiz edilip UserMemory + UserProfile'a işlenir,
// ardından bu zenginleştirilmiş profile göre AI antrenman + beslenme programı üretilir.
// ==========================================
function OnboardingWizard({ onComplete }) {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState({
    age: '', height: '', current_weight: '', target_weight: '',
    goal: 'recomp', target_physique: '', experience_months: '',
    focus_muscle_group: '', activity_level: 'moderate',
  });

  const [mediaError, setMediaError] = useState('');
  const [isRecording, setIsRecording] = useState(false);

  const [videoBlob, setVideoBlob] = useState(null);
  const [videoReport, setVideoReport] = useState(null);
  const [analyzingVideo, setAnalyzingVideo] = useState(false);

  const [audioBlob, setAudioBlob] = useState(null);
  const [voiceResult, setVoiceResult] = useState(null);
  const [analyzingVoice, setAnalyzingVoice] = useState(false);

  const [finishing, setFinishing] = useState(false);
  const [finishError, setFinishError] = useState('');

  const videoPreviewRef = useRef(null);
  const streamRef = useRef(null);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const autoStopTimerRef = useRef(null);

  const updateForm = (key, value) => setForm((f) => ({ ...f, [key]: value }));

  // Dosya boyutunu makul tutmak için (büyük video = yavaş/başarısız yükleme = "Load failed")
  // video bitrate'i sınırlıyoruz ve 20 saniyede otomatik durduruyoruz - fizik analizi için
  // bu süre zaten fazlasıyla yeterli.
  const MAX_RECORD_SECONDS = 20;
  const VIDEO_BITRATE = 1_200_000; // ~1.2 Mbps -> 20sn ~= 3MB civarı

  const startRecording = async (kind) => {
    setMediaError('');
    try {
      const constraints = kind === 'video'
        ? { video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } }, audio: true }
        : { audio: true };
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      streamRef.current = stream;
      if (kind === 'video' && videoPreviewRef.current) {
        videoPreviewRef.current.srcObject = stream;
        videoPreviewRef.current.play().catch(() => {});
      }
      chunksRef.current = [];
      const recorderOptions = kind === 'video' ? { videoBitsPerSecond: VIDEO_BITRATE } : {};
      const recorder = new MediaRecorder(stream, recorderOptions);
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: kind === 'video' ? 'video/webm' : 'audio/webm' });
        if (kind === 'video') setVideoBlob(blob); else setAudioBlob(blob);
        stream.getTracks().forEach((t) => t.stop());
        if (autoStopTimerRef.current) { clearTimeout(autoStopTimerRef.current); autoStopTimerRef.current = null; }
      };
      recorder.start();
      recorderRef.current = recorder;
      setIsRecording(true);
      if (kind === 'video') {
        autoStopTimerRef.current = setTimeout(() => {
          if (recorderRef.current && recorderRef.current.state === 'recording') recorderRef.current.stop();
        }, MAX_RECORD_SECONDS * 1000);
      }
    } catch (err) {
      console.error(err);
      setMediaError('Kamera/mikrofon erişimi alınamadı. Tarayıcı izinlerini kontrol edip tekrar dener misin?');
    }
  };

  const stopRecording = () => {
    recorderRef.current?.stop();
    setIsRecording(false);
  };

  // Backend hata dönerse (413 çok büyük dosya, 500 sunucu hatası vb.) JSON içindeki gerçek
  // "detail" mesajını gösteriyoruz; jenerik "bir şeyler ters gitti" yerine kullanıcı NE
  // yapması gerektiğini (örn. videoyu kısalt) doğrudan görsün diye.
  const extractErrorMessage = async (res, fallback) => {
    try {
      const data = await res.json();
      return data.detail || fallback;
    } catch {
      return fallback;
    }
  };

  const analyzeVideo = async () => {
    if (!videoBlob) return;
    setAnalyzingVideo(true);
    setMediaError('');
    try {
      const fd = new FormData();
      fd.append('file', videoBlob, 'body-scan.webm');
      const res = await fetch(`${API_BASE}/api/onboarding/video`, { method: 'POST', body: fd });
      if (!res.ok) {
        setMediaError(await extractErrorMessage(res, 'Video analiz edilemedi efendim, tekrar dener misin?'));
        return;
      }
      setVideoReport(await res.json());
    } catch (e) {
      console.error(e);
      setMediaError('Sunucuya bağlanılamadı. Backend çalışıyor mu ve video çok uzun değil mi kontrol eder misin?');
    } finally {
      setAnalyzingVideo(false);
    }
  };

  const analyzeVoice = async () => {
    if (!audioBlob) return;
    setAnalyzingVoice(true);
    setMediaError('');
    try {
      const fd = new FormData();
      fd.append('file', audioBlob, 'voice-note.webm');
      const res = await fetch(`${API_BASE}/api/onboarding/voice`, { method: 'POST', body: fd });
      if (!res.ok) {
        setMediaError(await extractErrorMessage(res, 'Ses kaydı analiz edilemedi efendim, tekrar dener misin?'));
        return;
      }
      setVoiceResult(await res.json());
    } catch (e) {
      console.error(e);
      setMediaError('Sunucuya bağlanılamadı. Backend çalışıyor mu kontrol eder misin?');
    } finally {
      setAnalyzingVoice(false);
    }
  };

  const finishOnboarding = async () => {
    setFinishing(true);
    setFinishError('');
    try {
      const payload = {
        age: form.age ? parseInt(form.age, 10) : null,
        height: form.height ? parseFloat(form.height) : null,
        current_weight: form.current_weight ? parseFloat(form.current_weight) : null,
        target_weight: form.target_weight ? parseFloat(form.target_weight) : null,
        goal: form.goal || null,
        target_physique: form.target_physique || null,
        experience_months: form.experience_months ? parseInt(form.experience_months, 10) : null,
        focus_muscle_group: form.focus_muscle_group || null,
        activity_level: form.activity_level || null,
      };
      const res = await fetch(`${API_BASE}/api/onboarding/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error('kurulum tamamlanamadı');
      await onComplete();
    } catch (e) {
      console.error(e);
      setFinishError('Kurulum tamamlanamadı efendim, tekrar dener misin?');
    } finally {
      setFinishing(false);
    }
  };

  const steps = ['Bilgiler', 'Vücut Videosu', 'Sesli Anlatım', 'Bitir'];

  return (
    <div className="min-h-screen bg-neutral-950 text-white font-mono p-4 flex flex-col items-center justify-center">
      <div className="max-w-lg w-full space-y-6">
        <div className="text-center space-y-2">
          <div className="w-16 h-16 bg-neutral-900 border border-neutral-800 rounded-full mx-auto flex items-center justify-center">
            <span className="text-3xl">🤖</span>
          </div>
          <h1 className="text-xl font-black tracking-widest text-orange-500">JARVIS KURULUMU</h1>
          <p className="text-xs text-neutral-500">Seni gerçekten tanıyıp sana özel bir program kurmam için birkaç adım.</p>
        </div>

        <div className="flex items-center gap-2">
          {steps.map((label, i) => (
            <div key={label} className="flex-1">
              <div className={`h-1 rounded-full ${i <= step ? 'bg-orange-500' : 'bg-neutral-800'}`}></div>
              <p className={`text-[10px] mt-1 text-center ${i === step ? 'text-orange-400' : 'text-neutral-600'}`}>{label}</p>
            </div>
          ))}
        </div>

        <div className="bg-neutral-900 border border-neutral-800 rounded-2xl p-6 space-y-5">

          {step === 0 && (
            <div className="space-y-4">
              <p className="text-sm text-neutral-300">Önce temel bilgilerini alalım efendim.</p>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <label className="space-y-1">
                  <span className="text-neutral-500">Yaş</span>
                  <input type="number" value={form.age} onChange={(e) => updateForm('age', e.target.value)}
                    className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-white" />
                </label>
                <label className="space-y-1">
                  <span className="text-neutral-500">Boy (cm)</span>
                  <input type="number" value={form.height} onChange={(e) => updateForm('height', e.target.value)}
                    className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-white" />
                </label>
                <label className="space-y-1">
                  <span className="text-neutral-500">Güncel kilo (kg)</span>
                  <input type="number" value={form.current_weight} onChange={(e) => updateForm('current_weight', e.target.value)}
                    className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-white" />
                </label>
                <label className="space-y-1">
                  <span className="text-neutral-500">Hedef kilo (kg)</span>
                  <input type="number" value={form.target_weight} onChange={(e) => updateForm('target_weight', e.target.value)}
                    className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-white" />
                </label>
                <label className="space-y-1 col-span-2">
                  <span className="text-neutral-500">Hedef</span>
                  <select value={form.goal} onChange={(e) => updateForm('goal', e.target.value)}
                    className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-white">
                    <option value="bulk">Kütle (Bulk)</option>
                    <option value="cut">Yağ Yakımı (Cut)</option>
                    <option value="recomp">Recomp</option>
                    <option value="maintain">Koruma</option>
                  </select>
                </label>
                <label className="space-y-1 col-span-2">
                  <span className="text-neutral-500">Hedef fizik (opsiyonel, örn. "geniş sırt, ince bel")</span>
                  <input type="text" value={form.target_physique} onChange={(e) => updateForm('target_physique', e.target.value)}
                    className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-white" />
                </label>
                <label className="space-y-1">
                  <span className="text-neutral-500">Antrenman tecrübesi (ay)</span>
                  <input type="number" value={form.experience_months} onChange={(e) => updateForm('experience_months', e.target.value)}
                    className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-white" />
                </label>
                <label className="space-y-1">
                  <span className="text-neutral-500">Aktivite seviyesi</span>
                  <select value={form.activity_level} onChange={(e) => updateForm('activity_level', e.target.value)}
                    className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-white">
                    <option value="sedentary">Hareketsiz</option>
                    <option value="light">Az hareketli</option>
                    <option value="moderate">Orta</option>
                    <option value="active">Aktif</option>
                  </select>
                </label>
                <label className="space-y-1 col-span-2">
                  <span className="text-neutral-500">Odak kas grubu (opsiyonel)</span>
                  <input type="text" value={form.focus_muscle_group} onChange={(e) => updateForm('focus_muscle_group', e.target.value)}
                    className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-white" />
                </label>
              </div>
              <button onClick={() => setStep(1)}
                className="w-full bg-orange-500 text-black font-bold py-3 rounded-xl text-sm">
                DEVAM ET →
              </button>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-4">
              <p className="text-sm text-neutral-300">
                Şimdi uygun/aydınlık bir ışıkta, önden ve yandan dönerek 15-20 saniyelik bir vücut videosu çek.
                Bu videoyu sana özel program kurmak için analiz edeceğim.
              </p>
              <div className="bg-black rounded-xl overflow-hidden aspect-video flex items-center justify-center border border-neutral-800">
                {videoBlob ? (
                  <video src={URL.createObjectURL(videoBlob)} controls className="w-full h-full object-contain" />
                ) : (
                  <video ref={videoPreviewRef} muted playsInline className="w-full h-full object-contain" />
                )}
              </div>
              {mediaError && <p className="text-xs text-red-400">{mediaError}</p>}
              <div className="flex gap-2">
                {!isRecording && !videoBlob && (
                  <button onClick={() => startRecording('video')} className="flex-1 bg-red-600 text-white font-bold py-2.5 rounded-xl text-xs">● KAYDI BAŞLAT</button>
                )}
                {isRecording && (
                  <button onClick={stopRecording} className="flex-1 bg-neutral-700 text-white font-bold py-2.5 rounded-xl text-xs animate-pulse">■ KAYDI DURDUR</button>
                )}
                {videoBlob && !videoReport && (
                  <>
                    <button onClick={() => setVideoBlob(null)} className="flex-1 bg-neutral-800 text-white font-bold py-2.5 rounded-xl text-xs">TEKRAR ÇEK</button>
                    <button onClick={analyzeVideo} disabled={analyzingVideo} className="flex-1 bg-orange-500 text-black font-bold py-2.5 rounded-xl text-xs disabled:opacity-50">
                      {analyzingVideo ? 'ANALİZ EDİLİYOR...' : 'ANALİZ ET'}
                    </button>
                  </>
                )}
              </div>
              {videoReport && (
                <div className="bg-neutral-950 border border-emerald-500/30 rounded-xl p-4 text-xs text-neutral-300 leading-relaxed max-h-40 overflow-y-auto">
                  {videoReport.report || 'Analiz tamamlandı.'}
                </div>
              )}
              <div className="flex justify-between text-xs pt-2">
                <button onClick={() => setStep(0)} className="text-neutral-500">← Geri</button>
                <button onClick={() => setStep(2)} className="text-orange-400 font-bold">
                  {videoBlob ? 'DEVAM ET →' : 'ATLA →'}
                </button>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <p className="text-sm text-neutral-300">
                Şimdi sesli olarak anlat: güncel beslenmen nasıl, hangi antrenmanları yapıyorsun,
                günlük rutinin/uyku düzenin nasıl ve gerçekte neye ulaşmak istiyorsun.
              </p>
              {mediaError && <p className="text-xs text-red-400">{mediaError}</p>}
              <div className="bg-neutral-950 border border-neutral-800 rounded-xl p-6 flex flex-col items-center gap-3">
                <span className="text-4xl">{isRecording ? '🔴' : '🎙️'}</span>
                {audioBlob && <audio src={URL.createObjectURL(audioBlob)} controls className="w-full" />}
                <div className="flex gap-2 w-full">
                  {!isRecording && !audioBlob && (
                    <button onClick={() => startRecording('audio')} className="flex-1 bg-red-600 text-white font-bold py-2.5 rounded-xl text-xs">● KAYDI BAŞLAT</button>
                  )}
                  {isRecording && (
                    <button onClick={stopRecording} className="flex-1 bg-neutral-700 text-white font-bold py-2.5 rounded-xl text-xs animate-pulse">■ KAYDI DURDUR</button>
                  )}
                  {audioBlob && !voiceResult && (
                    <>
                      <button onClick={() => setAudioBlob(null)} className="flex-1 bg-neutral-800 text-white font-bold py-2.5 rounded-xl text-xs">TEKRAR KAYDET</button>
                      <button onClick={analyzeVoice} disabled={analyzingVoice} className="flex-1 bg-orange-500 text-black font-bold py-2.5 rounded-xl text-xs disabled:opacity-50">
                        {analyzingVoice ? 'İŞLENİYOR...' : 'GÖNDER'}
                      </button>
                    </>
                  )}
                </div>
              </div>
              {voiceResult && (
                <div className="bg-neutral-950 border border-emerald-500/30 rounded-xl p-4 text-xs text-neutral-300 leading-relaxed max-h-40 overflow-y-auto space-y-2">
                  <p className="text-emerald-400 font-bold">Anladıklarım:</p>
                  <p>{voiceResult.summary || voiceResult.transcript}</p>
                </div>
              )}
              <div className="flex justify-between text-xs pt-2">
                <button onClick={() => setStep(1)} className="text-neutral-500">← Geri</button>
                <button onClick={() => setStep(3)} className="text-orange-400 font-bold">
                  {audioBlob ? 'DEVAM ET →' : 'ATLA →'}
                </button>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4 text-center">
              <p className="text-sm text-neutral-300">
                Her şey hazır efendim. Verdiğin bilgileri, video analizini ve sesli anlatımını
                birleştirip sana özel bir antrenman ve beslenme programı kuracağım.
              </p>
              {finishError && <p className="text-xs text-red-400">{finishError}</p>}
              <button onClick={finishOnboarding} disabled={finishing}
                className="w-full bg-orange-500 text-black font-bold py-3 rounded-xl text-sm disabled:opacity-50">
                {finishing ? 'PROGRAM OLUŞTURULUYOR...' : '🚀 PROGRAMIMI OLUŞTUR'}
              </button>
              <button onClick={() => setStep(2)} className="text-xs text-neutral-500">← Geri</button>
            </div>
          )}

        </div>

        <p className="text-center text-[10px] text-neutral-700">
          Alternatif olarak Telegram botuna gidip <code className="text-neutral-500">/profil</code> komutuyla da kurulum yapabilirsin.
        </p>
      </div>
    </div>
  );
}
