import React, { useState, useRef, useCallback } from 'react';

const API_BASE = 'http://127.0.0.1:8000';

const STEPS = [
  { id: 'video', title: 'Vücut Videosu', icon: '📹' },
  { id: 'nutrition', title: 'Beslenme', icon: '🍽️' },
  { id: 'training', title: 'Antrenman', icon: '🏋️' },
  { id: 'lifestyle', title: 'Günlük Yaşam', icon: '🌙' },
  { id: 'basics', title: 'Temel Bilgiler', icon: '📋' },
];

export default function OnboardingWizard({ onComplete }) {
  const [step, setStep] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [videoFile, setVideoFile] = useState(null);
  const [videoPreview, setVideoPreview] = useState(null);
  const [recordings, setRecordings] = useState({ nutrition: null, training: null, lifestyle: null });
  const [recording, setRecording] = useState(false);
  const [recordingType, setRecordingType] = useState(null);
  const [basics, setBasics] = useState({ age: '', height: '', weight: '', goal: '' });

  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const videoInputRef = useRef(null);

  const currentStep = STEPS[step];

  const handleVideoSelect = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setVideoFile(file);
    setVideoPreview(URL.createObjectURL(file));
    setError('');
  };

  const startRecording = useCallback(async (type) => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      mr.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        setRecordings((prev) => ({ ...prev, [type]: blob }));
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        setRecordingType(null);
      };
      mediaRecorderRef.current = mr;
      mr.start();
      setRecording(true);
      setRecordingType(type);
      setError('');
    } catch {
      setError('Mikrofon erişimi reddedildi. Tarayıcı ayarlarından izin verin.');
    }
  }, []);

  const stopRecording = () => {
    if (mediaRecorderRef.current?.state === 'recording') {
      mediaRecorderRef.current.stop();
    }
  };

  const canProceed = () => {
    const id = currentStep.id;
    if (id === 'video') return !!videoFile;
    if (id === 'nutrition') return !!recordings.nutrition;
    if (id === 'training') return !!recordings.training;
    if (id === 'lifestyle') return !!recordings.lifestyle;
    if (id === 'basics') return basics.age && basics.height && basics.weight && basics.goal;
    return false;
  };

  const submitOnboarding = async () => {
    setLoading(true);
    setError('');
    try {
      const form = new FormData();
      form.append('video', videoFile);
      form.append('nutrition_audio', recordings.nutrition, 'nutrition.webm');
      form.append('training_audio', recordings.training, 'training.webm');
      form.append('lifestyle_audio', recordings.lifestyle, 'lifestyle.webm');
      form.append('age', basics.age);
      form.append('height', basics.height);
      form.append('weight', basics.weight);
      form.append('goal', basics.goal);

      const res = await fetch(`${API_BASE}/api/onboarding/complete`, { method: 'POST', body: form });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Profil oluşturulamadı');
      }
      onComplete?.();
    } catch (e) {
      setError(e.message || 'Bir hata oluştu');
    } finally {
      setLoading(false);
    }
  };

  const next = () => {
    if (step < STEPS.length - 1) setStep(step + 1);
    else submitOnboarding();
  };

  const prompts = {
    nutrition: 'Güncel beslenmeni anlat: ne yiyorsun, kaç öğün, protein alımın, sevmediğin yiyecekler, alerjiler.',
    training: 'Güncel antrenmanını anlat: hangi günler, hangi hareketler, deneyim seviyen, sakatlık var mı.',
    lifestyle: 'Günlük yaşamını anlat: uyku saatlerin, iş/okul yoğunluğun, stres seviyen, ne zaman antrenman yapmayı tercih edersin.',
  };

  return (
    <div className="min-h-screen bg-neutral-950 text-white flex flex-col items-center justify-center font-sans p-4">
      <div className="max-w-lg w-full bg-neutral-900 border border-neutral-800 p-8 rounded-2xl space-y-6 shadow-2xl relative overflow-hidden">
        <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-orange-500 to-transparent" />

        <div className="text-center space-y-2">
          <span className="text-4xl">{currentStep.icon}</span>
          <h1 className="text-xl font-black tracking-widest text-orange-500">PROFİL OLUŞTUR</h1>
          <p className="text-xs font-mono text-neutral-500">
            Adım {step + 1}/{STEPS.length} — {currentStep.title}
          </p>
        </div>

        {/* Progress bar */}
        <div className="flex gap-1">
          {STEPS.map((s, i) => (
            <div
              key={s.id}
              className={`h-1 flex-1 rounded-full transition-colors ${i <= step ? 'bg-orange-500' : 'bg-neutral-800'}`}
            />
          ))}
        </div>

        {currentStep.id === 'video' && (
          <div className="space-y-4">
            <p className="text-sm text-neutral-400 leading-relaxed">
              Vücudunu <strong className="text-white">iyi aydınlatılmış</strong> bir ortamda, ön ve yan açılardan
              10-15 saniyelik bir video çek. Spor kıyafetiyle, aynada veya tripod ile kaydet.
            </p>
            <ul className="text-xs text-neutral-500 space-y-1 font-mono">
              <li>• Doğal veya parlak ışık kullan</li>
              <li>• Kollarını yanına indir, sonra hafifçe kaslarını göster</li>
              <li>• Yüzünü gizlemene gerek yok — sadece vücut analizi yapılacak</li>
            </ul>
            <input ref={videoInputRef} type="file" accept="video/*" capture="environment" className="hidden" onChange={handleVideoSelect} />
            <button
              onClick={() => videoInputRef.current?.click()}
              className="w-full py-4 border-2 border-dashed border-neutral-700 rounded-xl text-sm font-mono text-neutral-400 hover:border-orange-500 hover:text-orange-400 transition-colors"
            >
              {videoFile ? `✅ ${videoFile.name}` : '📹 Video Seç veya Kaydet'}
            </button>
            {videoPreview && (
              <video src={videoPreview} controls className="w-full rounded-xl border border-neutral-800 max-h-48" />
            )}
          </div>
        )}

        {['nutrition', 'training', 'lifestyle'].includes(currentStep.id) && (
          <div className="space-y-4">
            <p className="text-sm text-neutral-400 leading-relaxed">{prompts[currentStep.id]}</p>
            <div className="flex flex-col items-center gap-3 py-4">
              {!recordings[currentStep.id] ? (
                <button
                  onClick={() => (recording && recordingType === currentStep.id ? stopRecording() : startRecording(currentStep.id))}
                  className={`w-20 h-20 rounded-full flex items-center justify-center text-2xl transition-all ${
                    recording && recordingType === currentStep.id
                      ? 'bg-red-500 animate-pulse scale-110'
                      : 'bg-neutral-800 border-2 border-neutral-700 hover:border-orange-500'
                  }`}
                >
                  {recording && recordingType === currentStep.id ? '⏹' : '🎙️'}
                </button>
              ) : (
                <div className="text-center space-y-2">
                  <span className="text-emerald-400 text-sm font-mono">✅ Kayıt alındı</span>
                  <button
                    onClick={() => setRecordings((prev) => ({ ...prev, [currentStep.id]: null }))}
                    className="text-xs text-neutral-500 hover:text-orange-400 underline"
                  >
                    Yeniden kaydet
                  </button>
                </div>
              )}
              <p className="text-[10px] font-mono text-neutral-600">
                {recording && recordingType === currentStep.id ? 'Kaydediliyor... Durdurmak için tekrar bas' : 'Mikrofona bas ve konuş'}
              </p>
            </div>
          </div>
        )}

        {currentStep.id === 'basics' && (
          <div className="space-y-3">
            <p className="text-sm text-neutral-400">Son olarak birkaç temel bilgi — ses kayıtlarından çıkaramadığımız sayısal veriler:</p>
            {[
              ['age', 'Yaş', 'number'],
              ['height', 'Boy (cm)', 'number'],
              ['weight', 'Güncel Kilo (kg)', 'number'],
            ].map(([key, label, type]) => (
              <div key={key}>
                <label className="text-[10px] font-mono uppercase text-neutral-500">{label}</label>
                <input
                  type={type}
                  value={basics[key]}
                  onChange={(e) => setBasics({ ...basics, [key]: e.target.value })}
                  className="w-full mt-1 bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-orange-500"
                />
              </div>
            ))}
            <div>
              <label className="text-[10px] font-mono uppercase text-neutral-500">Hedefin</label>
              <input
                type="text"
                placeholder="örn: kas kütlesi artırmak, yağ yakmak, form korumak"
                value={basics.goal}
                onChange={(e) => setBasics({ ...basics, goal: e.target.value })}
                className="w-full mt-1 bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-orange-500"
              />
            </div>
          </div>
        )}

        {error && <p className="text-xs text-red-400 font-mono">{error}</p>}

        <div className="flex gap-3 pt-2">
          {step > 0 && (
            <button
              onClick={() => setStep(step - 1)}
              disabled={loading}
              className="flex-1 py-3 bg-neutral-800 text-neutral-300 text-xs font-bold rounded-lg hover:bg-neutral-700 disabled:opacity-50"
            >
              GERİ
            </button>
          )}
          <button
            onClick={next}
            disabled={!canProceed() || loading}
            className="flex-1 py-3 bg-orange-500 text-black text-xs font-bold rounded-lg disabled:opacity-40 hover:bg-orange-400 transition-colors"
          >
            {loading ? 'OLUŞTURULUYOR...' : step === STEPS.length - 1 ? 'PROFİLİ TAMAMLA' : 'DEVAM'}
          </button>
        </div>

        <p className="text-[10px] text-neutral-600 text-center font-mono">
          Telegram'dan da /profil ile aynı akışı başlatabilirsin
        </p>
      </div>
    </div>
  );
}
