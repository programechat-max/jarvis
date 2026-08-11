import React, { useState, useEffect, useCallback } from 'react';

const API_BASE = 'http://127.0.0.1:8000';

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
    return (
      <div className="min-h-screen bg-neutral-950 text-white flex flex-col items-center justify-center font-mono p-4">
        <div className="max-w-md w-full bg-neutral-900 border border-neutral-800 p-8 rounded-2xl text-center space-y-6 shadow-2xl relative overflow-hidden">
          <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-orange-500 to-transparent animate-pulse"></div>
          <div className="w-20 h-20 bg-neutral-950 border border-neutral-800 rounded-full mx-auto flex items-center justify-center mb-4">
            <span className="text-4xl">🤖</span>
          </div>
          <h1 className="text-2xl font-black tracking-widest text-orange-500">SİSTEM KİLİTLİ</h1>
          <p className="text-sm text-neutral-400 leading-relaxed">
            AI.COACH_OS başlatılamıyor. Telegram botuna henüz profil oluşturmadın ya da hiç rapor girmedin.
          </p>
          <div className="bg-neutral-950 p-4 rounded-xl border border-neutral-800 text-left text-xs space-y-2">
            <p className="text-emerald-400 font-bold">ÇÖZÜM:</p>
            <p className="text-neutral-500">Telegram botuna gidip <code className="text-orange-400">/profil</code> komutuyla profilini oluştur, sonra yediğin bir şeyi rapor et.</p>
          </div>
        </div>
      </div>
    );
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
              <p className="text-neutral-400 text-sm mt-1">Telegram'dan gönderdiğin her rapor 10 saniyede bir buraya otomatik yansıyacak şampiyon.</p>
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

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-2xl space-y-4">
                <h3 className="text-xs font-mono uppercase text-neutral-400 tracking-wider">Kilo Trendi</h3>
                {metrics.filter(m => m.weight).length === 0 ? (
                  <p className="text-sm text-neutral-600 font-mono">Henüz ölçüm yok.</p>
                ) : (
                  <>
                    <WeightSparkline metrics={metrics} />
                    {weightDelta !== null && (
                      <p className="text-xs font-mono text-neutral-400">
                        30 günde değişim: <span className={weightDelta <= 0 ? 'text-emerald-400' : 'text-orange-400'}>{weightDelta > 0 ? '+' : ''}{weightDelta.toFixed(1)} kg</span>
                      </p>
                    )}
                  </>
                )}
                <form onSubmit={submitWeight} className="flex gap-2 pt-2">
                  <input
                    type="number" step="0.1" placeholder="kg" value={weightInput}
                    onChange={(e) => setWeightInput(e.target.value)}
                    className="flex-1 bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-orange-500"
                  />
                  <button type="submit" disabled={savingWeight}
                    className="bg-orange-500 text-black text-xs font-bold px-4 py-2 rounded-lg disabled:opacity-50">
                    {savingWeight ? '...' : 'KAYDET'}
                  </button>
                </form>
              </div>

              <div className="lg:col-span-2 bg-neutral-900 border border-neutral-800 p-6 rounded-2xl space-y-4">
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

// Set sayısına göre ısı rengi belirler. Eşikler haftalık hipertrofi hacim standartlarına
// yaklaşık dayanır (haftada ~10-20 set/kas grubu optimal aralık kabul edilir).
function getHeatColor(sets) {
  if (!sets || sets === 0) return '#3f3f46';        // neutral-700 - hiç çalışılmamış (nötr gri gövde)
  if (sets <= 4) return '#78350f';                   // amber-900 - düşük
  if (sets <= 8) return '#f97316';                   // orange-500 - orta
  if (sets <= 14) return '#ea580c';                  // orange-600 - yüksek
  return '#dc2626';                                  // red-600 - çok yüksek
}

// Referans anatomi görseline benzer, ÖN ve ARKA gövdeyi yan yana gösteren ısı haritası.
// Nötr gri bir vücut siluetinin üzerine, o gün çalışılan kas gruplarını renklendiriyor.
// Kol ve Bacak hem ön (biceps/quad) hem arka (triceps/hamstring-glute) görünümde aynı
// renkte çıkar çünkü veri modelimizde bu ayrım yok, tek "Kol"/"Bacak" kategorisi var.
function MuscleHeatmap({ data }) {
  const sets = (group) => (data[group]?.sets) || 0;
  const c = (group) => getHeatColor(sets(group));
  const neutral = '#27272a'; // el, ayak, kafa gibi takip edilmeyen bölgeler

  const legendGroups = ['Göğüs', 'Sırt', 'Omuz', 'Kol', 'Karın', 'Bacak'];

  return (
    <div className="flex flex-col md:flex-row items-center gap-6">
      <svg viewBox="0 0 400 340" className="w-full max-w-md h-auto shrink-0">
        {/* ========== ÖN GÖRÜNÜM ========== */}
        <g>
          {/* Kafa + boyun */}
          <ellipse cx="95" cy="26" rx="15" ry="17" fill={neutral} />
          <rect x="87" y="40" width="16" height="14" rx="4" fill={neutral} />
          {/* Trapez (Sırt - önden az görünen kısım) */}
          <path d="M70,54 L95,46 L120,54 L112,62 L95,56 L78,62 Z" fill={c('Sırt')} />
          {/* Omuzlar (deltoid) */}
          <ellipse cx="62" cy="70" rx="15" ry="14" fill={c('Omuz')} />
          <ellipse cx="128" cy="70" rx="15" ry="14" fill={c('Omuz')} />
          {/* Göğüs (pektoral - iki parça, ortada birleşen) */}
          <path d="M95,60 C80,58 68,66 66,82 C65,96 78,108 95,104 L95,60 Z" fill={c('Göğüs')} />
          <path d="M95,60 C110,58 122,66 124,82 C125,96 112,108 95,104 L95,60 Z" fill={c('Göğüs')} />
          {/* Kollar (biceps) */}
          <path d="M50,80 C40,84 36,100 40,130 C42,145 48,152 54,150 C58,148 56,130 55,110 C54,95 56,84 50,80 Z" fill={c('Kol')} />
          <path d="M140,80 C150,84 154,100 150,130 C148,145 142,152 136,150 C132,148 134,130 135,110 C136,95 134,84 140,80 Z" fill={c('Kol')} />
          {/* Ön kollar (aynı grup, daha soluk ton verilmez - tutarlılık için aynı renk) */}
          <rect x="38" y="148" width="14" height="52" rx="6" fill={c('Kol')} />
          <rect x="138" y="148" width="14" height="52" rx="6" fill={c('Kol')} />
          {/* Karın (6 parçalı) */}
          {[0, 1, 2].map((row) => (
            <g key={row}>
              <rect x="80" y={108 + row * 17} width="13" height="14" rx="3" fill={c('Karın')} />
              <rect x="97" y={108 + row * 17} width="13" height="14" rx="3" fill={c('Karın')} />
            </g>
          ))}
          {/* Bacaklar (quad) */}
          <path d="M78,162 C70,180 68,220 72,260 C74,278 82,280 88,278 C92,276 92,240 90,210 C89,190 90,172 78,162 Z" fill={c('Bacak')} />
          <path d="M112,162 C120,180 122,220 118,260 C116,278 108,280 102,278 C98,276 98,240 100,210 C101,190 100,172 112,162 Z" fill={c('Bacak')} />
          {/* Alt bacak + ayak (nötr) */}
          <rect x="74" y="278" width="14" height="45" rx="6" fill={neutral} />
          <rect x="102" y="278" width="14" height="45" rx="6" fill={neutral} />
        </g>

        {/* ========== ARKA GÖRÜNÜM ========== */}
        <g transform="translate(210, 0)">
          <ellipse cx="95" cy="26" rx="15" ry="17" fill={neutral} />
          <rect x="87" y="40" width="16" height="14" rx="4" fill={neutral} />
          {/* Trapez + üst sırt */}
          <path d="M68,52 L95,44 L122,52 L118,80 L95,72 L72,80 Z" fill={c('Sırt')} />
          {/* Lats (kanat şeklinde geniş sırt kası) */}
          <path d="M72,80 C60,90 56,115 66,140 C74,155 88,158 95,150 L95,72 Z" fill={c('Sırt')} />
          <path d="M118,80 C130,90 134,115 124,140 C116,155 102,158 95,150 L95,72 Z" fill={c('Sırt')} />
          {/* Arka omuz */}
          <ellipse cx="62" cy="70" rx="14" ry="13" fill={c('Omuz')} />
          <ellipse cx="128" cy="70" rx="14" ry="13" fill={c('Omuz')} />
          {/* Triceps */}
          <path d="M50,80 C40,84 36,100 40,130 C42,145 48,152 54,150 C58,148 56,130 55,110 C54,95 56,84 50,80 Z" fill={c('Kol')} />
          <path d="M140,80 C150,84 154,100 150,130 C148,145 142,152 136,150 C132,148 134,130 135,110 C136,95 134,84 140,80 Z" fill={c('Kol')} />
          <rect x="38" y="148" width="14" height="52" rx="6" fill={c('Kol')} />
          <rect x="138" y="148" width="14" height="52" rx="6" fill={c('Kol')} />
          {/* Bel - alt sırt */}
          <path d="M83,150 L107,150 L104,168 L86,168 Z" fill={c('Sırt')} />
          {/* Kalça (glute) + hamstring - Bacak grubu */}
          <path d="M75,168 C68,172 66,190 70,205 C73,215 88,216 90,205 C92,195 90,178 85,168 Z" fill={c('Bacak')} />
          <path d="M115,168 C122,172 124,190 120,205 C117,215 102,216 100,205 C98,195 100,178 105,168 Z" fill={c('Bacak')} />
          <path d="M76,205 C72,225 72,250 76,270 C78,278 86,278 87,270 C88,250 88,225 84,208 Z" fill={c('Bacak')} />
          <path d="M114,205 C118,225 118,250 114,270 C112,278 104,278 103,270 C102,250 102,225 106,208 Z" fill={c('Bacak')} />
          <rect x="74" y="278" width="14" height="45" rx="6" fill={neutral} />
          <rect x="102" y="278" width="14" height="45" rx="6" fill={neutral} />
        </g>
      </svg>

      <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs font-mono w-full md:w-48 shrink-0">
        {legendGroups.map((group) => (
          <div key={group} className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-sm shrink-0" style={{ backgroundColor: getHeatColor(sets(group)) }}></span>
            <span className="text-neutral-400">{group}</span>
            <span className="text-neutral-300 ml-auto">{sets(group)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
