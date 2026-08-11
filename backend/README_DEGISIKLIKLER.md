# Bu düzenlemede neler değişti?

## Kritik düzeltmeler
- `main.py` artık gerçekten çalışıyor: eski hali `models.NutritionPlan.date` ve `target_fats`
  gibi VAR OLMAYAN kolonlara referans veriyordu, her istek 500 hatası veriyordu.
- Frontend'in beklediği `/api/status`, `/api/nutrition`, `/api/workout` endpoint'leri artık gerçekten var.
- Kırık/bağlanmamış `routers/` klasörü (var olmayan şema ve crud fonksiyonlarına referans veriyordu,
  hiçbir yerden import edilmiyordu) tamamen kaldırıldı.
- `ai_agent.py` (hiç kullanılmıyordu) ve `telegram_bot.py`'deki ayrı, senkron olmayan AI mantığı
  tek bir `ai_core.py` motorunda birleştirildi.
- `NutritionPlan` tablosu `date` kolonu olmadığı için "bugünün öğünleri" hiç doğru çekilemiyordu;
  yeni `NutritionLog` tablosu bunu düzeltiyor.

## Yeni eklenen (senin istediğin kişiselleştirme + gelişim takibi için)
- `UserProfile` genişletildi: hedef, aktivite seviyesi, beslenme/uyku/sakatlık notları, günlük makro hedefleri.
- Telegram'da `/profil` komutu ile onboarding sohbeti: yaş, boy, kilo, hedef, aktivite, beslenme, rutin sorup profili dolduruyor.
- `BodyMetric` tablosu: kilo/ölçüm geçmişi (gelişim grafiği için).
- `UserMemory` tablosu: AI'nin öğrendiği tercihler ve haftalık analizler kalıcı olarak saklanıyor,
  her mesajda system prompt'a otomatik ekleniyor (Jarvis gerçekten "seni tanıyor").
- `/analiz` komutu ve haftalık otomatik (Pazartesi 09:00) analiz: son 7 günün antrenman/beslenme/kilo
  verisini AI analiz edip somut öneriler veriyor - "gelişime yönelik hareket etme" isteğinin başlangıcı.
- `video_analyzer.py` artık analiz sonucunu bir .txt dosyasına değil, veritabanına yazıyor -
  eskiden telegram_bot.py bu dosyayı hiç okumadığı için video analizleri botu etkilemiyordu.

## Sırada ne var (senin onayınla devam edeceğim)
1. Frontend'i (`App.jsx`) yeni endpoint'lere göre güncellemek — özellikle sabit 2700kcal/140g
   hedeflerini profildeki gerçek `daily_calorie_target` değerlerine bağlamak.
2. Antrenman programının "progressive overload" mantığıyla otomatik ilerlemesi (örn. hedef tekrara
   ulaşıldıysa ağırlığı otomatik önerme).
3. Dashboard'a gelişim grafiği (kilo/ölçüm trendi) ve haftalık analiz kartı eklemek.
4. `.env` dosyasını `.env.example`'dan oluşturup gerçek anahtarları girmen gerekiyor.
