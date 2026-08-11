"""
Jarvis'in tek ve birleşik AI motoru.
Önceden ai_agent.py'de yapılandırılmış intent analizi, telegram_bot.py'de ise
ayrı ve senkron olmayan bir sohbet mantığı vardı. Bu dosya ikisini birleştirir:
- Kullanıcı profilini ve son verilerini okuyarak GERÇEK ZAMANLI, kişiselleştirilmiş
  bir system prompt üretir (statik metin değil).
- Tek bir JSON şemasıyla intent + yanıt üretir (yemek, antrenman, kilo, sohbet).
- Video analizinden veya haftalık analizden çıkan içgörüleri veritabanındaki
  UserMemory tablosundan okur (artık bir .txt dosyası değil).
"""
import os
import json
import logging
import re
from datetime import date, timedelta

import google.generativeai as genai
from dotenv import load_dotenv

import crud
import progression
from database import SessionLocal

load_dotenv()
logger = logging.getLogger(__name__)

API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=API_KEY)

MODEL_NAME = "gemini-2.5-flash"

BASE_PERSONA = """
Sen kullanıcının kişisel 'Jarvis' adındaki elit, sadık ve zeki fitness/sağlık asistanısın.
Iron Man filmindeki Jarvis gibi asil, sadık, hafif nüktedan ve tamamen kullanıcı odaklısın.
Kullanıcıya her zaman "efendim" diye hitap et. Kuru, robotik onay cümleleri kurma;
onunla gerçek bir koç gibi, doğal ve samimi konuş. Yanlış bir bilgi varsa nazikçe düzelt.

BİLİŞSEL YETENEKLERİN (her mesajda uygula):
1. Önce kullanıcının GERÇEK niyetini çıkar — kelimelere değil, bağlama bak.
2. Türkçe'deki günlük konuşma, kısaltma, yazım hatası ve sesli mesaj bozukluklarını tolere et.
3. "Plan" ile "bugün yediklerim" ayrımını kesin yap: plan = öneri/menü, log = gerçekte yenen.
4. Belirsizlikte en mantıklı yorumu seç; kullanıcıyı gereksiz yere sorgulama.
5. Kullanıcının geçmiş hafızası, bugünkü kayıtları ve beslenme planı birlikte değerlendir.
"""


def build_system_prompt(db=None) -> str:
    """Kullanıcının profilini, son 7 günlük verilerini ve AI'nin biriktirdiği
    hafızayı okuyarak DİNAMİK bir system prompt üretir. Bu, uygulamanın
    'kullanıcının hayatına göre' davranmasını sağlayan ana mekanizmadır."""
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        profile = crud.get_or_create_profile(db)
        memories = crud.get_recent_memories(db, limit=10)

        profile_block = f"""
KULLANICI PROFİLİ:
- Yaş: {profile.age or 'bilinmiyor'}, Boy: {profile.height or 'bilinmiyor'} cm, Güncel kilo: {profile.current_weight or 'bilinmiyor'} kg
- Hedef: {profile.goal} ({profile.target_physique or 'belirtilmedi'}), Hedef kilo: {profile.target_weight or 'belirtilmedi'}
- Antrenman deneyimi: {profile.experience_months or 0} ay, Odak: {profile.focus_muscle_group or 'genel'}
- Aktivite seviyesi: {profile.activity_level}
- Beslenme tercihleri / kısıtlamalar: {profile.dietary_notes or 'belirtilmedi'}
- Günlük rutin / uyku notları: {profile.schedule_notes or 'belirtilmedi'}
- Sakatlık / kısıtlama notları: {profile.injury_notes or 'yok'}
- Günlük hedefler: {profile.daily_calorie_target} kcal, {profile.daily_protein_target}g protein,
  {profile.daily_carb_target}g karbonhidrat, {profile.daily_fat_target}g yağ
"""

        if memories:
            mem_lines = "\n".join(f"- ({m.category}) {m.content}" for m in memories)
            memory_block = f"\nJARVIS'İN KULLANICI HAKKINDA BİRİKTİRDİĞİ HAFIZA:\n{mem_lines}\n"
        else:
            memory_block = "\n(Henüz kayıtlı bir hafıza yok - kullanıcıyı tanımaya başlıyorsun.)\n"

        meal_plan = crud.get_meal_plan(db)
        if meal_plan:
            plan_lines = "\n".join(
                f"- {m.meal_name} ({m.time_target}): {m.description} "
                f"[{m.calories:.0f} kcal, {m.protein:.0f}g P, {m.carbs:.0f}g K, {m.fats:.0f}g Y]"
                for m in meal_plan
            )
            plan_block = f"\nGÜNCEL BESLENME PLANI (kullanıcı 'planımdaki X'i yedim' derse buradan eşleştir):\n{plan_lines}\n"
        else:
            plan_block = "\n(Kayıtlı bir beslenme planı yok - kullanıcı 'planımdaki X'i yedim' derse plan olmadığını söyle ve ne yediğini sor.)\n"

        return BASE_PERSONA + profile_block + memory_block + plan_block
    finally:
        if own_session:
            db.close()


INTENT_INSTRUCTIONS = """
GÖREVİN: Kullanıcının mesajını DERİNLEMESİNE analiz et ve SADECE aşağıdaki JSON formatında yanıt dön.
JSON dışında hiçbir şey yazma.

ÖNCE DÜŞÜN (reasoning alanına yaz), SONRA karar ver:
- Kullanıcı ne YAPMAK istiyor? (kaydet / sor / değiştir / sil / sohbet)
- Beslenme PLANINA mı atıf yapıyor, yoksa rastgele bir şey mi yedi?
- Tek öğün mü, TÜM plan/menü mü?
- Geçmiş konuşma bağlamı var mı?

{
  "reasoning": "2-4 cümle: mesajı nasıl yorumladığın, neden bu intent'i seçtiğin (kullanıcıya gösterilmez)",
  "intent": "log_food" | "log_workout" | "log_weight" | "remember" | "query_history" | "modify_meal_plan" | "delete_meal_plan" | "delete_food_log" | "modify_workout_program" | "delete_workout_program" | "chat",
  "confidence": "high" | "medium" | "low",
  "data": {
    // log_food — KRİTİK BESLENME ANLAMA KURALLARI:
    //
    // A) SOMUT TARİF (plan dışı): Kullanıcı ne yediğini malzeme/miktar ile anlattı
    //    (örn. "3 yumurta yedim", "150g tavuk pirinç"). description'a yaz, makroları hesapla.
    //    matched_plan_meal: null, log_entire_plan: false.
    //
    // B) TEK PLAN ÖĞÜNÜ: Kullanıcı planındaki BİR öğünü yedi
    //    (örn. "planımdaki kahvaltıyı yedim", "öğle yemeğimi yedim", "akşam öğünü tamam").
    //    matched_plan_meal: GÜNCEL BESLENME PLANI listesindeki TAM meal_name (örn. "Kahvaltı").
    //    log_entire_plan: false. Makrolar: 0 (sistem plandan alır).
    //
    // C) TÜM PLAN / TÜM ÖĞÜNLER — log_entire_plan: true, matched_plan_meal: null
    //    Şu ifadelerin HEPSİ bu kategoridedir (tek öğün SANMA):
    //    - "tüm öğünlerimi yedim", "bütün öğünlerimi yedim", "hepsini yedim"
    //    - "bugünkü beslenme programımı uyguladım", "günün menüsünü yedim"
    //    - "plana uygun yedim", "beslenme planıma sadık kaldım"
    //    - "tüm planı yedim", "menüyü bitirdim", "3 öğünün hepsini yedim"
    //    - "önerdiğin planı uyguladım", "programa göre yedim"
    //    ÖNEMLİ: "tüm öğünlerimi" bir meal_name DEĞİLDİR — asla matched_plan_meal olarak yazma!
    //
    // D) Belirsiz ama yemek kaydı niyeti: somut tarif sor, uydurma yapma.

    // log_workout ise: "sets" adında bir LİSTE ver. Kullanıcı tek mesajda birden fazla
    //   hareket veya set anlatabilir (örn. "bench 4x8 60kg, sonra dips 3x12 vücut ağırlığı") -
    //   HER SETİ AYRI BİR ELEMAN OLARAK LİSTEYE EKLE:
    //   "sets": [
    //     {"exercise_name": "Bench Press", "set_number": 1, "weight_lifted": 60, "reps_done": 8, "rpe": 8},
    //     {"exercise_name": "Bench Press", "set_number": 2, "weight_lifted": 60, "reps_done": 7, "rpe": 9}
    //   ]
    //   KURALLAR:
    //   - weight_lifted ve reps_done HER ZAMAN sayı olmalı, asla "Varying", "değişken" gibi
    //     metin yazma. Ağırlık set set değiştiyse HER SET İÇİN AYRI ELEMAN oluştur ve o setin
    //     gerçek sayısını yaz.
    //   - Vücut ağırlığı hareketlerinde (mekik, dips, pull-up vb.) weight_lifted için 0 yaz.
    //   - Kullanıcı set sayısını veya tekrarı belirtmediyse mantıklı bir varsayım yap
    //     (örn. sadece "bench yaptım" derse tek set, reps_done tahmini yap) ama sayı olsun.
    //   - Türkçe hareket adlarını İngilizce standart isme çevir (göğüs presi → Bench Press).

    // log_weight ise: "weight", "waist", "chest", "arm", "sleep_hours"
    // remember ise: "category" ("preference"|"note"), "content"
    //   (kullanıcı kalıcı bir tercih, alışkanlık veya yaşam tarzı bilgisi paylaştıysa kullan,
    //    örn: "balık yemem", "akşamları geç yatıyorum", "dizimde eski bir sakatlık var")
    // query_history ise: "days_ago" (int, kaç gün önce - "dün"=1, "bugün"=0, "geçen hafta"=7,
    //   belirtilmemişse veya "bu hafta/son günler" gibi genel bir aralıksa 7 yaz)
    //   BU INTENT'İ KULLAN: kullanıcı geçmişte ne yaptığını/yediğini soruyorsa
    //   (örn: "dün ne yemiştim", "geçen hafta antrenman yaptım mı", "bugün kaç kalori aldım").
    //   jarvis_reply'i BOŞ BIRAK ("") - gerçek veri ayrıca eklenecek, sen tahmin ile cevap UYDURMA.

    // modify_meal_plan ise: "instruction" (kullanıcının isteğinin TAM VE DETAYLI hali -
    //   kullanıcı miktar/malzeme belirttiyse HİÇBİRİNİ ATLAMADAN aynen yaz, kısaltma/yorumlama)
    //   BU INTENT'İ KULLAN: kullanıcı mevcut planı DEĞİŞTİRMEK istiyorsa - bir öğünü,
    //   içeriği veya kaloriyi güncellemek istiyor (örn: "kahvaltıyı değiştir", "tavuk yerine
    //   balık koy", "daha az kalorili yap", "akşam yemeğini çıkar"). jarvis_reply'i BOŞ BIRAK ("")
    //   - plan ayrıca yeniden oluşturulup gerçek sonuç eklenecek.
    //   ÖNEMLİ: kullanıcı belirli bir öğünü BİREBİR ne yiyeceğini tarif ettiyse (örn: "5 yumurta,
    //   3'ünün sarısı var, 2 patates kabuklu fırında, 1 yemek kaşığı zeytinyağı"), bunu KENDİ
    //   YORUMUNLA DEĞİŞTİRME veya BAŞKA MALZEMELERLE DEĞİŞTİRME - kullanıcının verdiği malzeme ve
    //   miktarları AYNEN instruction'a yaz, plan oluşturma aşamasında bu birebir kullanılacak.
    //   DİKKAT: kullanıcı planın TAMAMINI kaldırmak/silmek istiyorsa bunu KULLANMA,
    //   onun yerine delete_meal_plan kullan.

    // delete_meal_plan ise: veri gerekmez, boş obje {} yeterli.
    //   BU INTENT'İ KULLAN: kullanıcı önerilen BESLENME planını (henüz yenmemiş, gelecekteki
    //   öneri) tamamen SİLMEK/KALDIRMAK istiyorsa (örn: "beslenme planımı kaldır", "menüyü sil").
    //   DİKKAT: kullanıcı "bugün YEDİĞİM şeyleri sil/kaldır" diyorsa bu DEĞİL, delete_food_log
    //   kullan. DİKKAT: kullanıcı "ANTRENMAN programını/planını sil" diyorsa bu KESİNLİKLE DEĞİL,
    //   onun yerine delete_workout_program kullan - "beslenme/menü/yemek" ile "antrenman/spor/
    //   program" kelimelerini KARIŞTIRMA, ikisi tamamen ayrı tablolardır.

    // delete_food_log ise: "days_ago" (int, kaç gün önce - belirtilmemişse 0 = bugün)
    //   BU INTENT'İ KULLAN: kullanıcı GERÇEKTE yediği/kaydedilen öğünleri silmek istiyorsa
    //   (örn: "bugün yediklerimi sil", "yanlışlıkla girmişim, kaldır", "yemek kaydımı temizle").
    //   jarvis_reply'i BOŞ BIRAK ("").

    // delete_workout_program ise: veri gerekmez, boş obje {} yeterli.
    //   BU INTENT'İ KULLAN: kullanıcı ANTRENMAN PROGRAMINI tamamen SİLMEK/KALDIRMAK istiyorsa
    //   (örn: "antrenman programını sil", "spor planımı kaldır", "programı temizle").
    //   BUNU beslenme/yemek ile İLGİLİ hiçbir şeyle karıştırma. jarvis_reply'i BOŞ BIRAK ("").

    // modify_workout_program ise: "instruction" (kullanıcının isteğinin TAM VE DETAYLI hali)
    //   BU INTENT'İ KULLAN: kullanıcı antrenman PROGRAMINI oluşturmak/değiştirmek istiyorsa
    //   (örn: "bana bir program yap", "pazartesi gününü değiştir", "bacak gününe squat ekle",
    //   "hiç programım yok, oluştursana"). Bunu tek bir SET/hareket KAYDETMEK (log_workout) ile
    //   KARIŞTIRMA - kullanıcı "yaptım" diyorsa log_workout, "program/plan yapsana/değiştir"
    //   diyorsa modify_workout_program. Kullanıcı programı SİLMEK istiyorsa bunu değil
    //   delete_workout_program kullan. jarvis_reply'i BOŞ BIRAK ("").
  },
  "jarvis_reply": "Kullanıcıya Jarvis tonunda, kişiselleştirilmiş, kısa ve motive edici yanıt."
}

KARMAŞIK TÜRKÇE ANLAMA ÖRNEKLERİ (bunları doğru sınıflandır):
| Mesaj | intent | data özeti |
| "tüm öğünlerimi yedim" | log_food | log_entire_plan: true |
| "hepsini yedim bugün" | log_food | log_entire_plan: true (plan varsa) |
| "planımdaki kahvaltıyı yedim" | log_food | matched_plan_meal: "Kahvaltı" |
| "öğle yemeğimi yedim" | log_food | matched_plan_meal: plan listesinden eşleşen |
| "3 yumurta 2 dilim ekmek yedim" | log_food | somut tarif, plan yok |
| "bugünkü programı uyguladım" | log_food | log_entire_plan: true |
| "beslenme planımı sil" | delete_meal_plan | {} |
| "bugün yediklerimi sil" | delete_food_log | days_ago: 0 |
| "dün ne yemiştim" | query_history | days_ago: 1 |
| "bench 3x8 60kg yaptım" | log_workout | sets listesi |
| "programımı değiştir bacak günü ekle" | modify_workout_program | instruction |

Not: Bir mesajda birden fazla şey olabilir (örn. hem yemek hem tercih) - sadece EN BASKIN
intent'i seç, ama jarvis_reply içinde ikisini de yanıtlayabilirsin.
"""


def _safe_float(value, default=0.0):
    """AI bazen 'Varying', 'vücut ağırlığı' gibi metinler döndürebiliyor -
    bu durumda çökmek yerine güvenli bir varsayılana düş."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    return int(_safe_float(value, default))


def _normalize_text(text: str) -> str:
    """Türkçe karakterleri sadeleştirip küçük harfe çevirir — eşleştirme için."""
    if not text:
        return ""
    text = text.lower().strip()
    tr_map = str.maketrans("ıİğĞüÜşŞöÖçÇ", "iigguussoocc")
    return text.translate(tr_map)


# Yaygın öğün ifadeleri → plan öğün adlarıyla eşleştirme ipuçları
MEAL_ALIASES = {
    "kahvalti": ["kahvaltı", "sabah", "sabah ogunu", "sabah öğünü", "breakfast", "1. ogun", "1. öğün", "birinci ogun"],
    "ogle": ["öğle", "öğlen", "ogle yemegi", "öğle yemeği", "lunch", "2. ogun", "2. öğün", "ikinci ogun", "oglen"],
    "aksam": ["akşam", "aksam yemegi", "akşam yemeği", "dinner", "gece yemegi", "gece yemeği", "3. ogun", "3. öğün"],
    "ara": ["ara ogun", "ara öğün", "atistirmalik", "atıştırmalık", "snack", "ikindi"],
}

# Tüm planı kaydetme ifadeleri — çoğul öğün, plan/program/menü ve günlük konuşma varyantları
WHOLE_PLAN_RE = re.compile(
    r"(?:"
    r"tum\s+(?:plan(?:im(?:i)?|a)?|menu(?:m(?:u)?)?|beslenme(?:\s+plan(?:im(?:i)?|a)?)?|"
    r"ogun(?:ler(?:im(?:i)?|ini|i)?)?|yemek(?:ler(?:im(?:i)?|ini|i)?)?)|"
    r"butun\s+(?:plan(?:im(?:i)?|a)?|menu(?:m(?:u)?)?|ogun(?:ler(?:im(?:i)?|ini|i)?)?|"
    r"yemek(?:ler(?:im(?:i)?|ini|i)?)?|beslenme)|"
    r"(?:ogun|yemek)lerim(?:i|in|in\s+hepsi|in\s+tamami)?|"
    r"(?:hepsi|tamami|tumu)\s+(?:ogun|yemek|menu|plan)|"
    r"hepsini\s+(?:yedim|aldim|bitirdim|tamamladim|uyguladim)|"
    r"(?:beslenme\s+)?(?:program|plan)(?:im|imi|a)?\s*(?:uygula|uyguladim|takip|yedim|bitirdim|tamamladim|aldim)|"
    r"(?:bugunku|gunun|bugunun)\s+(?:beslenme\s+)?(?:program|plan|menu)(?:im|imi|a)?|"
    r"(?:program|plan|menu)(?:a|ima|im)?\s*(?:uygun|gore|dogru)\s*(?:yedim|aldim|uyguladim)|"
    r"onerd(?:igin|iginiz)\s+(?:plan|menu|beslenme)|"
    r"jarvis(?:'?in|in)?\s+(?:plan|menu|beslenme)|"
    r"menu(?:yu|yu\s+)?(?:yedim|uyguladim|bitirdim|tamamladim)|"
    r"plana?\s+(?:uygun|gore|sadik)\s*(?:yedim|kaldim|uyguladim)|"
    r"(?:\d+|uc|dort|bes|alti)\s+ogun(?:un)?\s+(?:hepsi|tamami|tumu)"
    r")",
    re.IGNORECASE,
)

# Tek öğün sanılıp aslında tüm plan olan ifadeler (AI/kural hata önleme)
WHOLE_PLAN_HINT_BLOCKLIST = re.compile(
    r"(?:"
    r"tum|butun|hepsi|tamami|tumu|ogunler|yemekler|menu|plan(?:im|a)?|program(?:im|a)?|"
    r"beslenme|gunun|bugunku|onerdigin|onerilen"
    r")",
    re.IGNORECASE,
)

PLAN_REFERENCE_RE = re.compile(
    r"(?:plan(?:im)?daki|program(?:im)?daki|menu(?:m)?deki|plandan|programdan|onerdigin|onerilen)",
    re.IGNORECASE,
)

LOG_ACTION_RE = re.compile(
    r"(?:yedim|yaptim|uyguladim|takip\s+ettim|bitirdim|tamamladim|aldim|tükettim|tukettim|girdim)",
    re.IGNORECASE,
)


def find_plan_meal(plan_items, query: str):
    """Plan öğününü esnek eşleştirir: tam ad, kısmi ad, alias veya benzerlik."""
    if not plan_items or not query:
        return None

    q = _normalize_text(query)
    if not q:
        return None

    # 1) Tam eşleşme
    for item in plan_items:
        if _normalize_text(item.meal_name) == q:
            return item

    # 2) Birinin diğerini içermesi
    for item in plan_items:
        name = _normalize_text(item.meal_name)
        if q in name or name in q:
            return item

    # 3) Alias → plan adı
    for alias_key, aliases in MEAL_ALIASES.items():
        terms = [_normalize_text(alias_key)] + [_normalize_text(a) for a in aliases]
        if any(term in q for term in terms):
            for item in plan_items:
                name = _normalize_text(item.meal_name)
                if any(term in name for term in terms) or alias_key in name:
                    return item

    # 4) difflib ile en yakın isim
    from difflib import get_close_matches
    name_map = {_normalize_text(item.meal_name): item for item in plan_items}
    close = get_close_matches(q, list(name_map.keys()), n=1, cutoff=0.55)
    if close:
        return name_map[close[0]]

    return None


def _extract_raw_meal_hint(message: str) -> str | None:
    """Mesajdan olası tek öğün ipucunu çıkarır (tüm plan filtresi uygulanmaz)."""
    msg = _normalize_text(message)

    m = re.search(r"plan(?:im)?daki\s+(.+?)(?:\s+yedim|\s+aldim|\s+uyguladim|$)", msg)
    if m:
        return m.group(1).strip()

    m = re.search(r"program(?:im)?daki\s+(.+?)(?:\s+yedim|\s+aldim|\s+uyguladim|$)", msg)
    if m:
        return m.group(1).strip()

    for alias_key, aliases in MEAL_ALIASES.items():
        terms = [_normalize_text(alias_key)] + [_normalize_text(a) for a in aliases]
        if any(term in msg for term in terms):
            return alias_key

    return None


def _is_whole_plan_hint(hint: str) -> bool:
    """Çıkarılan ipucunun aslında 'tüm plan' anlamına gelip gelmediğini kontrol eder."""
    if not hint:
        return False
    h = _normalize_text(hint)
    if WHOLE_PLAN_RE.search(h):
        return True
    if WHOLE_PLAN_HINT_BLOCKLIST.search(h) and not find_plan_meal_keyword(h):
        return True
    return False


def find_plan_meal_keyword(hint: str) -> bool:
    """İpucunda bilinen tek öğün alias'ı var mı."""
    h = _normalize_text(hint)
    for alias_key, aliases in MEAL_ALIASES.items():
        terms = [_normalize_text(alias_key)] + [_normalize_text(a) for a in aliases]
        if any(term in h for term in terms):
            return True
    return False


def _extract_meal_hint_from_message(message: str) -> str | None:
    """Mesajdan hangi TEK öğüne atıf yapıldığını çıkarır. Tüm plan ifadelerinde None döner."""
    if _wants_whole_plan_log(message):
        return None

    hint = _extract_raw_meal_hint(message)
    if hint and _is_whole_plan_hint(hint):
        return None
    return hint


def _wants_whole_plan_log(message: str) -> bool:
    msg = _normalize_text(message)
    if WHOLE_PLAN_RE.search(msg):
        return True
    if LOG_ACTION_RE.search(msg) and re.search(
        r"(?:tum|butun|hepsi|tamami|tumu)\s*(?:ogun|yemek)|"
        r"(?:ogun|yemek)lerim(?:i|in)?|"
        r"hepsini\s+(?:ogun|yemek|menu)",
        msg,
    ):
        return True
    if LOG_ACTION_RE.search(msg) and re.search(r"(?:beslenme\s+)?(?:program|plan|menu)", msg):
        hint = _extract_raw_meal_hint(message)
        if not hint or _is_whole_plan_hint(hint):
            return True
    return False


def _wants_plan_meal_log(message: str) -> bool:
    if _wants_whole_plan_log(message):
        return False
    msg = _normalize_text(message)
    if PLAN_REFERENCE_RE.search(msg):
        return True
    if _extract_meal_hint_from_message(message) and LOG_ACTION_RE.search(msg):
        return True
    if re.search(r"(?:kahvalti|ogle|aksam|ara\s+ogun|atistirmalik).*(?:yedim|aldim|uyguladim)", msg):
        return True
    return False


def _log_plan_meal(db, plan_item) -> dict:
    """Tek plan öğününü bugünün beslenme kaydına yazar."""
    import schemas
    crud.create_nutrition_log(db, schemas.NutritionLogCreate(
        meal_name=plan_item.meal_name,
        ingredients=plan_item.description,
        calories=plan_item.calories,
        protein=plan_item.protein,
        carbs=plan_item.carbs,
        fats=plan_item.fats,
    ))
    return {
        "intent": "log_food",
        "jarvis_reply": (
            f"✅ {plan_item.meal_name} kaydedildi efendim ({plan_item.calories:.0f} kcal, "
            f"{plan_item.protein:.0f}g protein) — plandaki haliyle."
        ),
        "_food_reply_is_final": True,
    }


def _log_all_plan_meals(db, plan_items) -> dict:
    """Plandaki tüm öğünleri bugüne kaydeder."""
    import schemas
    total_cal, total_prot = 0.0, 0.0
    names = []
    for item in plan_items:
        crud.create_nutrition_log(db, schemas.NutritionLogCreate(
            meal_name=item.meal_name,
            ingredients=item.description,
            calories=item.calories,
            protein=item.protein,
            carbs=item.carbs,
            fats=item.fats,
        ))
        total_cal += item.calories or 0
        total_prot += item.protein or 0
        names.append(item.meal_name)

    meal_list = ", ".join(names)
    return {
        "intent": "log_food",
        "jarvis_reply": (
            f"✅ Bugünkü beslenme planının tamamını kaydettim efendim: {meal_list}.\n"
            f"Toplam: {total_cal:.0f} kcal, {total_prot:.0f}g protein."
        ),
        "_food_reply_is_final": True,
    }


def _no_plan_reply() -> dict:
    return {
        "intent": "chat",
        "jarvis_reply": (
            "Kayıtlı bir beslenme planın yok efendim. Önce /beslenme yazıp planı oluştur "
            "ve ✅ Onayla butonuna bas; sonra 'planımdaki kahvaltıyı yedim' veya "
            "'bugünkü beslenme programımı uyguladım' diyebilirsin."
        ),
        "_food_reply_is_final": True,
    }


def _plan_meals_list_reply(plan_items) -> dict:
    names = ", ".join(p.meal_name for p in plan_items)
    return {
        "intent": "chat",
        "jarvis_reply": (
            f"Planında şu öğünler var efendim: {names}.\n"
            f"Hangi öğünü yedin? Örneğin: 'planımdaki kahvaltıyı yedim' veya "
            f"'bugünkü beslenme programımı uyguladım' diyebilirsin."
        ),
        "_food_reply_is_final": True,
    }


def build_operational_context(db, conversation_history: list | None = None) -> str:
    """AI'nin anlamlandırması için bugünkü durum + son konuşma bağlamını üretir."""
    today = date.today()
    meals_today = crud.get_nutrition_logs_by_date(db, today)
    plan_items = crud.get_meal_plan(db)
    workout_today = crud.get_workout_logs_by_date(db, today)

    lines = [f"\nOPERASYONEL BAĞLAM (bugün: {today.strftime('%A %d.%m.%Y')}):"]

    if plan_items:
        plan_names = ", ".join(p.meal_name for p in plan_items)
        plan_cal = sum(p.calories or 0 for p in plan_items)
        lines.append(f"- Aktif beslenme planı ({len(plan_items)} öğün): {plan_names} (toplam ~{plan_cal:.0f} kcal)")
    else:
        lines.append("- Aktif beslenme planı YOK")

    if meals_today:
        logged_cal = sum(m.calories or 0 for m in meals_today)
        logged_names = ", ".join(m.meal_name for m in meals_today)
        lines.append(f"- Bugün kayıtlı öğünler ({len(meals_today)}): {logged_names} ({logged_cal:.0f} kcal)")
    else:
        lines.append("- Bugün henüz öğün kaydı YOK")

    if workout_today:
        lines.append(f"- Bugün {len(workout_today)} antrenman seti kayıtlı")

    if conversation_history:
        recent = conversation_history[-6:]
        if recent:
            lines.append("- Son konuşma:")
            for turn in recent:
                role = "Kullanıcı" if turn.get("role") == "user" else "Jarvis"
                text = (turn.get("text") or "")[:200]
                lines.append(f"  {role}: {text}")

    lines.append("")
    return "\n".join(lines)


def validate_and_correct_food_intent(user_message: str, data: dict, plan_items) -> dict:
    """AI'nin sık yaptığı beslenme intent hatalarını kural tabanlı düzeltir."""
    data = dict(data or {})

    if _wants_whole_plan_log(user_message):
        data["log_entire_plan"] = True
        data["matched_plan_meal"] = None
        return data

    matched_name = data.get("matched_plan_meal")
    if matched_name and _is_whole_plan_hint(str(matched_name)):
        data["log_entire_plan"] = True
        data["matched_plan_meal"] = None
        return data

    if matched_name and plan_items:
        if not find_plan_meal(plan_items, matched_name):
            hint = _extract_meal_hint_from_message(user_message)
            if hint:
                corrected = find_plan_meal(plan_items, hint)
                if corrected:
                    data["matched_plan_meal"] = corrected.meal_name

    if not data.get("log_entire_plan") and not data.get("matched_plan_meal"):
        hint = _extract_meal_hint_from_message(user_message)
        if hint and plan_items:
            matched = find_plan_meal(plan_items, hint)
            if matched:
                data["matched_plan_meal"] = matched.meal_name

    return data


def _format_user_prompt(user_message: str, conversation_history: list | None = None) -> str:
    """Kullanıcı mesajını bağlamla birlikte modele iletir."""
    if not conversation_history:
        return user_message
    recent = conversation_history[-4:]
    if not recent:
        return user_message
    ctx_lines = []
    for turn in recent:
        if turn.get("role") == "user" and turn.get("text") == user_message:
            continue
        role = "Kullanıcı" if turn.get("role") == "user" else "Jarvis"
        ctx_lines.append(f"{role}: {turn.get('text', '')[:300]}")
    if not ctx_lines:
        return user_message
    return (
        "Önceki konuşma:\n" + "\n".join(ctx_lines) +
        f"\n\nŞimdiki mesaj:\n{user_message}"
    )


def try_resolve_plan_food_locally(user_message: str, db) -> dict | None:
    """AI'ye gitmeden plan tabanlı yemek kaydını çözmeye çalışır."""
    plan_items = crud.get_meal_plan(db)
    msg_norm = _normalize_text(user_message)

    refers_to_plan = (
        _wants_whole_plan_log(user_message)
        or _wants_plan_meal_log(user_message)
        or PLAN_REFERENCE_RE.search(_normalize_text(user_message))
    )

    if not plan_items:
        if refers_to_plan:
            return _no_plan_reply()
        return None

    # Tüm plan
    if _wants_whole_plan_log(user_message):
        return _log_all_plan_meals(db, plan_items)

    # Tek öğün
    if _wants_plan_meal_log(user_message):
        hint = _extract_meal_hint_from_message(user_message)
        if hint:
            matched = find_plan_meal(plan_items, hint)
            if matched:
                return _log_plan_meal(db, matched)

        # "planımdaki X'i yedim" ama X net değil — kullanıcıya seçenekleri göster
        if PLAN_REFERENCE_RE.search(_normalize_text(user_message)) and LOG_ACTION_RE.search(msg_norm):
            return _plan_meals_list_reply(plan_items)

    return None


def process_message(user_message: str, db=None, conversation_history: list | None = None) -> dict:
    """Tek giriş noktası: mesajı analiz eder, intent'e göre veritabanına yazar
    ve kullanıcıya verilecek yanıtı döndürür. Telegram botu ve ileride
    API/chat endpoint'i bu fonksiyonu kullanır."""
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        # Plan tabanlı yemek kaydı — AI'den önce kural tabanlı çöz (daha güvenilir)
        local_food = try_resolve_plan_food_locally(user_message, db)
        if local_food:
            return local_food

        operational_context = build_operational_context(db, conversation_history)
        system_instruction = build_system_prompt(db) + operational_context + INTENT_INSTRUCTIONS
        model = genai.GenerativeModel(model_name=MODEL_NAME, system_instruction=system_instruction)

        prompt = _format_user_prompt(user_message, conversation_history)
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json", "temperature": 0.25},
        )
        result = json.loads(response.text)
        intent = result.get("intent")
        data = result.get("data", {}) or {}

        if intent == "log_food":
            import schemas
            plan_items = crud.get_meal_plan(db)
            data = validate_and_correct_food_intent(user_message, data, plan_items)

            if data.get("log_entire_plan"):
                if plan_items:
                    result.update(_log_all_plan_meals(db, plan_items))
                else:
                    result.update(_no_plan_reply())
            else:
                matched_meal_name = data.get("matched_plan_meal")
                matched = None

                if matched_meal_name:
                    matched = find_plan_meal(plan_items, matched_meal_name)

                if not matched and plan_items:
                    hint = _extract_meal_hint_from_message(user_message)
                    if hint:
                        matched = find_plan_meal(plan_items, hint)
                    if not matched and _wants_whole_plan_log(user_message):
                        result.update(_log_all_plan_meals(db, plan_items))
                        matched = "__logged_all__"

                if matched == "__logged_all__":
                    pass
                elif matched:
                    result.update(_log_plan_meal(db, matched))
                elif matched_meal_name or _wants_plan_meal_log(user_message):
                    if _wants_whole_plan_log(user_message) and plan_items:
                        result.update(_log_all_plan_meals(db, plan_items))
                    elif plan_items:
                        result["jarvis_reply"] = (
                            f"Planında '{matched_meal_name or 'bu öğün'}' bulamadım efendim. "
                            f"Mevcut öğünler: {', '.join(p.meal_name for p in plan_items)}.\n"
                            f"Hangi öğünü yedin? Veya tüm planı yediysen 'tüm öğünlerimi yedim' diyebilirsin."
                        )
                        result["intent"] = "chat"
                        result["_food_reply_is_final"] = True
                    else:
                        result.update(_no_plan_reply())
                else:
                    calories = _safe_float(data.get("calories"), default=None)
                    description = data.get("description", "").strip()
                    if calories is None and not description:
                        result["jarvis_reply"] = (
                            "Ne yediğini biraz daha tarif eder misin efendim? (örn. '3 yumurta ve "
                            "1 dilim ekmek' gibi) - net bir tarif olmadan makroları uyduramam."
                        )
                        result["intent"] = "chat"
                    else:
                        crud.create_nutrition_log(db, schemas.NutritionLogCreate(
                            meal_name=data.get("meal_name", "Öğün"),
                            ingredients=description or user_message,
                            calories=_safe_float(data.get("calories")),
                            protein=_safe_float(data.get("protein")),
                            carbs=_safe_float(data.get("carbs")),
                            fats=_safe_float(data.get("fats")),
                        ))
        elif intent == "log_workout":
            import schemas
            # AI'den birden fazla set (çoklu hareket / farklı ağırlıklar) gelebilir.
            # Geriye dönük uyumluluk için tek set formatını da destekliyoruz.
            sets = data.get("sets")
            if not sets:
                sets = [data] if data else []

            logged_count = 0
            failed_count = 0
            new_prs = []
            for s in sets:
                try:
                    rpe_raw = s.get("rpe")
                    exercise_name = s.get("exercise_name", "Hareket")
                    weight_lifted = _safe_float(s.get("weight_lifted"))

                    # PR (kişisel rekor) tespiti - set kaydedilmeden ÖNCE mevcut en yüksek
                    # ağırlıkla karşılaştırılıyor. 0 ağırlıklı (vücut ağırlığı) hareketlerde
                    # PR anlamsız olduğu için atlanıyor.
                    previous_max = crud.get_max_weight_for_exercise(db, exercise_name)
                    if weight_lifted > 0 and weight_lifted > previous_max:
                        new_prs.append((exercise_name, weight_lifted, previous_max))

                    crud.log_workout_set(db, schemas.WorkoutLogCreate(
                        exercise_name=exercise_name,
                        set_number=_safe_int(s.get("set_number"), default=1) or 1,
                        weight_lifted=weight_lifted,
                        reps_done=_safe_int(s.get("reps_done")),
                        rpe=_safe_int(rpe_raw, default=None) if rpe_raw is not None else None,
                    ))
                    logged_count += 1
                except Exception as set_err:
                    logger.error(f"[AI_CORE] Set kaydı hatası (atlandı): {set_err} - veri: {s}")
                    failed_count += 1

            result["_sets_logged"] = logged_count
            result["_sets_failed"] = failed_count
            result["_new_prs"] = new_prs
        elif intent == "log_weight":
            import schemas
            crud.create_body_metric(db, schemas.BodyMetricCreate(
                weight=_safe_float(data.get("weight"), default=None) if data.get("weight") is not None else None,
                waist=_safe_float(data.get("waist"), default=None) if data.get("waist") is not None else None,
                chest=_safe_float(data.get("chest"), default=None) if data.get("chest") is not None else None,
                arm=_safe_float(data.get("arm"), default=None) if data.get("arm") is not None else None,
                sleep_hours=_safe_float(data.get("sleep_hours"), default=None) if data.get("sleep_hours") is not None else None,
            ))
        elif intent == "remember":
            crud.create_memory(db, category=data.get("category", "preference"), content=data.get("content", user_message))
        elif intent == "query_history":
            days_ago = _safe_int(data.get("days_ago"), default=7)
            target_date = date.today() - timedelta(days=days_ago)

            meals = crud.get_nutrition_logs_by_date(db, target_date)
            sets = crud.get_workout_logs_by_date(db, target_date)
            body = crud.get_body_metrics(db, days=days_ago + 1)
            body_that_day = [m for m in body if m.date == target_date]

            if not meals and not sets and not body_that_day:
                result["jarvis_reply"] = (
                    f"{target_date.strftime('%d %B')} tarihine ait hiç kayıt bulamadım efendim - "
                    f"o gün için bana hiçbir şey raporlamamışsın."
                )
            else:
                data_lines = [f"TARİH: {target_date}"]
                if meals:
                    total_cal = sum(m.calories or 0 for m in meals)
                    total_prot = sum(m.protein or 0 for m in meals)
                    data_lines.append(f"Öğünler ({total_cal:.0f} kcal, {total_prot:.0f}g protein toplam):")
                    for m in meals:
                        data_lines.append(f"  - {m.meal_name}: {m.calories:.0f} kcal, {m.protein:.0f}g protein")
                else:
                    data_lines.append("Öğün kaydı yok.")

                if sets:
                    data_lines.append("Antrenman setleri:")
                    for s in sets:
                        data_lines.append(f"  - {s.exercise_name}: set {s.set_number}, {s.weight_lifted}kg x {s.reps_done}")
                else:
                    data_lines.append("Antrenman kaydı yok.")

                if body_that_day:
                    for b in body_that_day:
                        if b.weight:
                            data_lines.append(f"Kilo: {b.weight}kg")

                summary_prompt = (
                    "Aşağıdaki GERÇEK veritabanı kaydını kullanıcıya Jarvis tonunda özetle. "
                    "Sadece verilen veriyi kullan, hiçbir şey uydurma:\n\n" + "\n".join(data_lines)
                )
                summary_model = genai.GenerativeModel(model_name=MODEL_NAME, system_instruction=BASE_PERSONA)
                summary_response = summary_model.generate_content(summary_prompt, generation_config={"temperature": 0.3})
                result["jarvis_reply"] = summary_response.text

        elif intent == "modify_meal_plan":
            instruction = data.get("instruction", user_message)
            updated_items = generate_meal_plan(db, user_instruction=instruction)
            if updated_items:
                lines = ["📋 Planı güncelledim efendim:\n"]
                for item in updated_items:
                    lines.append(f"🍴 {item.meal_name} ({item.time_target}): {item.description} — {item.calories:.0f} kcal")
                result["jarvis_reply"] = "\n".join(lines)
            else:
                result["jarvis_reply"] = "Planı güncellerken bir sorun oldu efendim, tekrar dener misin?"

        elif intent == "delete_meal_plan":
            crud.clear_meal_plan(db)
            result["jarvis_reply"] = (
                "🗑️ Beslenme planını kaldırdım efendim. İstediğin zaman /beslenme yazarak "
                "veya dashboard'dan yeni bir tane oluşturabilirsin."
            )

        elif intent == "delete_food_log":
            days_ago = _safe_int(data.get("days_ago"), default=0)
            target_date = date.today() - timedelta(days=days_ago)
            deleted_count = crud.clear_nutrition_logs_by_date(db, target_date)
            if deleted_count:
                gun_ifadesi = "bugünkü" if days_ago == 0 else f"{target_date.strftime('%d %B')} tarihli"
                result["jarvis_reply"] = f"🗑️ {gun_ifadesi} {deleted_count} öğün kaydını sildim efendim."
            else:
                result["jarvis_reply"] = "O tarihe ait zaten hiç yemek kaydın yoktu efendim."

        elif intent == "delete_workout_program":
            crud.clear_workout_programs(db)
            result["jarvis_reply"] = (
                "🗑️ Antrenman programını kaldırdım efendim. İstediğin zaman /antrenman yazarak "
                "veya dashboard'dan yeni bir tane oluşturabilirsin."
            )

        elif intent == "modify_workout_program":
            instruction = data.get("instruction", user_message)
            programs = generate_workout_program(db, user_instruction=instruction)
            if programs:
                lines = ["🏋️ Programı güncelledim efendim:\n"]
                for p in programs:
                    ex_summary = ", ".join(f"{e.name} ({e.target_sets}x{e.target_reps})" for e in p.exercises)
                    lines.append(f"📅 {p.day_name}: {ex_summary}")
                result["jarvis_reply"] = "\n".join(lines)
            else:
                result["jarvis_reply"] = "Programı güncellerken bir sorun oldu efendim, tekrar dener misin?"

        return result
    except Exception as e:
        logger.error(f"[AI_CORE] Mesaj işleme hatası: {e}")
        return {
            "intent": "chat",
            "data": {},
            "jarvis_reply": "Sistemlerimde ufak bir senkronizasyon hatası oluştu efendim, tekrar dener misiniz?",
        }
    finally:
        if own_session:
            db.close()


PLAN_INTERVIEW_QUESTIONS = [
    ("meal_count", "Günde kaç öğün yemek istersin? (örn: 3 ana öğün, veya 3 ana + 2 ara öğün)"),
    ("liked_foods", "Sevdiğin, sık yemek istediğin besinler neler? (örn: tavuk, yumurta, pirinç...)"),
    ("disliked_foods", "Hiç yemediğin veya sevmediğin besinler var mı?"),
    ("cooking_time", "Yemek hazırlamaya ne kadar vaktin oluyor genelde? (hızlı/pratik mi, uzun tarifler de olur mu)"),
    ("budget", "Bütçe konusunda bir kısıtlaman var mı? (kısıtlı / normal / önemli değil)"),
]

WORKOUT_INTERVIEW_QUESTIONS = [
    ("days_per_week", "Haftada kaç gün antrenman yapabiliyorsun?"),
    ("session_duration", "Bir antrenman ortalama kaç dakika sürüyor / sürmesini istersin?"),
    ("equipment", "Nerede antrenman yapıyorsun ve nelere erişimin var? (tam donanımlı salon / ev, dambıl vb. / sadece vücut ağırlığı)"),
    ("preferred_style", "Tercih ettiğin bir antrenman tarzı var mı? (örn. ağırlık odaklı, kardiyo katkılı, fonksiyonel)"),
    ("avoid_exercises", "Kaçınmak istediğin veya yapamadığın hareketler var mı? (sakatlık dışında, sevmediğin hareketler)"),
]


def build_plan_draft_from_answers(db, answers: dict, kind: str) -> list:
    """Anket cevaplarını user_instruction'a çevirip ilgili generate fonksiyonunu
    save=False ile çağırır - sonuç DB'ye yazılmadan önce kullanıcıya gösterilecek taslaktır."""
    instruction_lines = [f"{q}: {a}" for q, a in answers.items() if a]
    instruction = "Kullanıcının anket cevapları:\n" + "\n".join(instruction_lines)

    if kind == "nutrition":
        return generate_meal_plan(db, user_instruction=instruction, save=False)
    else:
        return generate_workout_program(db, user_instruction=instruction, save=False)


def refine_draft(db, draft_items: list, kind: str, user_feedback: str) -> list:
    """Kullanıcı taslağı onaylamayıp 'şunu değiştir' dediğinde, mevcut TASLAĞI (henüz
    kaydedilmemiş) baz alarak günceller - sıfırdan üretmez, DB'ye de yazmaz."""
    instruction = f"Az önce önerdiğin taslak üzerinde şu değişikliği yap: {user_feedback}"
    if kind == "nutrition":
        return generate_meal_plan(db, user_instruction=instruction, save=False, existing_override=draft_items)
    else:
        return generate_workout_program(db, user_instruction=instruction, save=False, existing_override=draft_items)


def persist_draft(db, draft_items: list, kind: str):
    """Kullanıcı 'onaylıyorum' dediğinde taslağı gerçek tabloya yazar.
    draft_items, save=False ile üretilmiş pydantic obje listesidir (dict değil)."""
    import schemas
    if kind == "nutrition":
        items = [schemas.MealPlanItemCreate(**i.model_dump()) for i in draft_items]
        return crud.replace_meal_plan(db, items)
    else:
        crud.clear_workout_programs(db)
        for p in draft_items:
            program_schema = schemas.WorkoutProgramCreate(
                day_name=p.day_name, is_active=True,
                exercises=[schemas.ExerciseCreate(**ex.model_dump()) for ex in p.exercises],
            )
            crud.create_workout_program(db, program_schema)
        # Aynı DetachedInstanceError nedeniyle ORM nesneleri değil, çağıranın zaten
        # elinde tuttuğu (ve DB'ye bağımlı olmayan) draft_items'ı geri döndürüyoruz.
        return draft_items


def generate_meal_plan(db=None, user_instruction: str = None, save: bool = True, existing_override: list = None):
    """Profildeki günlük hedeflere (kalori/makro) ve kısıtlamalara (dietary_notes) göre
    tam bir günlük öğün planı üretir. Bu, 'beslenme programı oluşturma' isteğinin karşılığıdır -
    NutritionLog'dan farklı olarak burada ÖNERİ üretiliyor, gerçek yenen değil.

    user_instruction verilirse (örn. "kahvaltıyı değiştir", "daha az kalorili yap"), mevcut plan
    o talimata göre DÜZENLENİR - sıfırdan yazılmaz, sadece istenen kısım değişir.

    save=False verilirse veritabanına YAZMADAN, pydantic obje listesi olarak döner - kullanıcı
    önce planı onaylasın diye (anket/onay akışı). save=True (varsayılan) direkt DB'ye yazar.

    existing_override verilirse, "mevcut plan" olarak DB yerine bu liste kullanılır - henüz
    kaydedilmemiş bir TASLAK üzerinde düzenleme yapmak için (onay akışında kullanılır)."""
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        profile = crud.get_or_create_profile(db)
        system_instruction = build_system_prompt(db)
        model = genai.GenerativeModel(model_name=MODEL_NAME, system_instruction=system_instruction)

        existing_plan = existing_override if existing_override is not None else crud.get_meal_plan(db)
        existing_block = ""
        if user_instruction and existing_plan:
            existing_lines = "\n".join(
                f"- {p.meal_name} ({p.time_target}): {p.description} "
                f"[{p.calories:.0f} kcal, {p.protein:.0f}g protein, {p.carbs:.0f}g karb, {p.fats:.0f}g yağ]"
                for p in existing_plan
            )
            existing_block = f"""
MEVCUT PLAN:
{existing_lines}

KULLANICININ İSTEĞİ: "{user_instruction}"

Yukarıdaki isteği uygula. Kullanıcı sadece belirli bir öğünden bahsettiyse SADECE onu değiştir,
geri kalan öğünleri MÜMKÜN OLDUĞUNCA AYNI bırak. Toplam kalori/makroyu hedeflere yakın tut.

KRİTİK KURAL: Kullanıcı bir öğün için SPESİFİK malzeme/miktar belirttiyse (örn. "5 yumurta,
3'ünün sarısı var", "2 patates kabuklu fırında") bu malzemeleri ve miktarları AYNEN kullan,
kendi yorumunla başka malzemeye çevirme veya "eşdeğeri" ile değiştirme. description alanına
kullanıcının verdiği tarifi olabildiğince birebir yansıt, sadece kalori/makro hesabını sen yap.
"""

        prompt = f"""
Kullanıcı için GÜNLÜK bir öğün planı oluştur. Aşağıdaki hedeflere MÜMKÜN OLDUĞUNCA yakın ol
(toplam kalori/protein/karbonhidrat/yağ):
- Hedef kalori: {profile.daily_calorie_target}
- Hedef protein: {profile.daily_protein_target}g
- Hedef karbonhidrat: {profile.daily_carb_target}g
- Hedef yağ: {profile.daily_fat_target}g

Kullanıcının beslenme kısıtlamaları/tercihleri: {profile.dietary_notes or 'belirtilmedi'}
Kullanıcının hedefi: {profile.goal}
{existing_block}
3-5 öğün olacak şekilde (kahvaltı, öğle, akşam, gerekirse ara öğün) SADECE aşağıdaki JSON
formatında bir liste dön, başka hiçbir şey yazma:

[
  {{"meal_name": "Kahvaltı", "time_target": "08:00", "description": "...", "calories": 500, "protein": 35, "carbs": 40, "fats": 15}},
  ...
]
"""
        response = model.generate_content(
            prompt, generation_config={"response_mime_type": "application/json", "temperature": 0.6}
        )
        raw_items = json.loads(response.text)

        import schemas
        items = [schemas.MealPlanItemCreate(**item) for item in raw_items]
        if not save:
            return items
        saved = crud.replace_meal_plan(db, items)
        return saved
    except Exception as e:
        logger.error(f"[AI_CORE] Öğün planı oluşturma hatası: {e}")
        return []
    finally:
        if own_session:
            db.close()


def generate_workout_program(db=None, user_instruction: str = None, save: bool = True, existing_override: list = None):
    """Profildeki hedef/deneyim/odak bölgeye göre haftalık antrenman programı üretir.
    user_instruction verilirse mevcut programı sıfırdan değil, o talimata göre düzenler.

    save=False verilirse DB'ye yazmadan pydantic obje listesi (WorkoutProgramCreate) döner -
    kullanıcı önce onaylasın diye. save=True (varsayılan) direkt DB'ye yazar.

    existing_override verilirse, DB yerine bu liste "mevcut program" olarak kullanılır -
    henüz kaydedilmemiş bir TASLAK üzerinde düzenleme yapmak için."""
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        profile = crud.get_or_create_profile(db)
        system_instruction = build_system_prompt(db)
        model = genai.GenerativeModel(model_name=MODEL_NAME, system_instruction=system_instruction)

        existing_programs = existing_override if existing_override is not None else crud.get_workout_programs(db)
        existing_block = ""
        if user_instruction and existing_programs:
            existing_lines = "\n".join(
                f"{p.day_name}: " + ", ".join(f"{e.name} ({e.target_sets}x{e.target_reps})" for e in p.exercises)
                for p in existing_programs
            )
            existing_block = f"""
MEVCUT PROGRAM:
{existing_lines}

KULLANICININ İSTEĞİ: "{user_instruction}"
Bu isteği uygula. Bahsedilmeyen günleri/hareketleri mümkün olduğunca aynı bırak.
"""

        prompt = f"""
Kullanıcı için HAFTALIK bir antrenman programı oluştur.
- Deneyim: {profile.experience_months or 0} ay
- Hedef: {profile.goal}, Odak bölge: {profile.focus_muscle_group or 'genel/dengeli'}
- Aktivite seviyesi: {profile.activity_level}
- Sakatlık/kısıtlama notları: {profile.injury_notes or 'yok'} (varsa bu bölgeleri zorlayan hareketlerden kaçın)
{existing_block}
3-5 antrenman günü oluştur (örn. "Pazartesi - İtiş (Göğüs/Omuz/Triceps)"). Her gün için 4-6 hareket,
her hareket için hedef set sayısı, tekrar aralığı ("8-12" gibi) ve HANGİ ANA KAS GRUBUNU
çalıştırdığını (muscle_group: "Göğüs", "Sırt", "Bacak", "Omuz", "Kol", "Karın" gibi TEK bir
kelime/grup - haftalık hacim takibi için bu alan ZORUNLU) belirt.

SADECE aşağıdaki JSON formatında bir liste dön, başka hiçbir şey yazma:
[
  {{"day_name": "Pazartesi - İtiş Günü", "exercises": [
    {{"name": "Bench Press", "target_sets": 4, "target_reps": "8-12", "muscle_group": "Göğüs"}},
    {{"name": "Shoulder Press", "target_sets": 3, "target_reps": "10-12", "muscle_group": "Omuz"}}
  ]}},
  ...
]
"""
        response = model.generate_content(
            prompt, generation_config={"response_mime_type": "application/json", "temperature": 0.6}
        )
        raw_programs = json.loads(response.text)

        import schemas
        program_schemas = [
            schemas.WorkoutProgramCreate(
                day_name=p["day_name"],
                is_active=True,
                exercises=[schemas.ExerciseCreate(**ex) for ex in p.get("exercises", [])],
            )
            for p in raw_programs
        ]
        if not save:
            return program_schemas

        crud.clear_workout_programs(db)
        for ps in program_schemas:
            crud.create_workout_program(db, ps)
        # ÖNEMLİ: ORM nesnelerini (saved) değil, program_schemas'ı (düz pydantic objeleri)
        # döndürüyoruz. ORM nesnelerinin 'exercises' ilişkisi lazy-load'dur; çağıran taraf
        # (örn. finish_onboarding) veritabanı oturumunu kapattıktan SONRA .exercises'e erişirse
        # DetachedInstanceError patlıyordu. program_schemas zaten session'dan bağımsız, düz
        # Python objeleri olduğu için session kapansa da güvenle okunabiliyor.
        return program_schemas
    except Exception as e:
        logger.error(f"[AI_CORE] Antrenman programı oluşturma hatası: {e}")
        return []
    finally:
        if own_session:
            db.close()


def generate_weekly_analysis(db=None) -> str:
    """Son 7 günün antrenman + beslenme + kilo verisini analiz edip
    kullanıcıya elit bir koç raporu üretir ve UserMemory'e 'analysis' olarak kaydeder.
    Bu fonksiyon, uygulamanın 'gelişime yönelik hareket etmesini' sağlayan parçadır."""
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        workout_logs = crud.get_workout_logs_range(db, days=7)
        nutrition_history = crud.get_nutrition_history(db, days=7)
        body_metrics = crud.get_body_metrics(db, days=14)
        profile = crud.get_or_create_profile(db)
        meal_plan = crud.get_meal_plan(db)

        # Plan vs gerçek tüketim karşılaştırması - önceden hiç yapılmıyordu
        if meal_plan:
            planned_cal = sum(m.calories for m in meal_plan)
            planned_prot = sum(m.protein for m in meal_plan)
            days_with_data = [d for d in nutrition_history if d["calories"] > 0]
            if days_with_data:
                avg_actual_cal = sum(d["calories"] for d in days_with_data) / len(days_with_data)
                avg_actual_prot = sum(d["protein"] for d in days_with_data) / len(days_with_data)
                plan_adherence = (
                    f"Planlanan günlük hedef: {planned_cal:.0f} kcal, {planned_prot:.0f}g protein.\n"
                    f"Son {len(days_with_data)} günün ortalama GERÇEK alımı: {avg_actual_cal:.0f} kcal, "
                    f"{avg_actual_prot:.0f}g protein.\n"
                    f"Fark: {avg_actual_cal - planned_cal:+.0f} kcal, {avg_actual_prot - planned_prot:+.0f}g protein."
                )
            else:
                plan_adherence = "Planlanmış bir menü var ama son 7 günde hiç gerçek öğün kaydı girilmemiş."
        else:
            plan_adherence = "Şu an aktif bir beslenme planı yok."

        deload = progression.check_deload_needed(db)
        volume = crud.get_weekly_volume_by_muscle_group(db, days=7)
        if deload["needs_deload"]:
            deload_summary = (
                f"DELOAD UYARISI TETİKLENDİ - durağan hareketler: {deload['stagnant_exercises']}, "
                f"yüksek yorgunluk: {deload['high_fatigue_exercises']}"
            )
        else:
            deload_summary = "Deload gerektiren bir durum yok, ilerleme sağlıklı görünüyor."

        data_summary = f"""
Son 7 gün antrenman kayıtları ({len(workout_logs)} set):
{[f"{w.exercise_name}: {w.weight_lifted}kg x {w.reps_done} (RPE {w.rpe})" for w in workout_logs]}

Kas grubu başına haftalık hacim (set sayısı): {volume}

{deload_summary}

Son 7 gün beslenme (gün/kalori/protein):
{nutrition_history}

PLAN vs GERÇEK TÜKETİM:
{plan_adherence}

Son 14 gün vücut ölçümleri:
{[f"{m.date}: {m.weight}kg" for m in body_metrics if m.weight]}
"""
        system_instruction = build_system_prompt(db)
        model = genai.GenerativeModel(model_name=MODEL_NAME, system_instruction=system_instruction)
        prompt = f"""
Aşağıda kullanıcının son verileri var. Elit bir koç gibi bunu analiz et:
1. Antrenman hacmi ve ilerleme (progressive overload oluyor mu?) yorumla. Kas grubu başına
   hacim dengesini de değerlendir (bir grup ihmal ediliyor mu?).
2. DELOAD UYARISI tetiklendiyse bunu MUTLAKA açıkça belirt ve neden gerektiğini açıkla.
3. Beslenme planına ne kadar sadık kalınmış (PLAN vs GERÇEK TÜKETİM bölümüne bak) - hedefin
   altında/üstünde kalınıyorsa bunu açıkça belirt ve nedenini sorgula.
4. Kilo/ölçüm trendini hedefle ({profile.goal}) tutarlılığı açısından yorumla.
5. Somut, uygulanabilir 2-3 öneri ver (örn: "bu hafta bench ağırlığını 2.5kg artır",
   "protein alımını artırmak için X ekle", "akşam öğününü planına daha yakın tutmayı dene").
Kısa, net ve Jarvis tonunda yaz.

VERİ:
{data_summary}
"""
        response = model.generate_content(prompt, generation_config={"temperature": 0.5})
        analysis_text = response.text
        crud.create_memory(db, category="analysis", content=analysis_text)
        return analysis_text
    except Exception as e:
        logger.error(f"[AI_CORE] Haftalık analiz hatası: {e}")
        return "Efendim, haftalık analizi şu an oluşturamadım, sistemlerde küçük bir aksaklık var."
    finally:
        if own_session:
            db.close()


def analyze_physique_media(media_bytes: bytes, mime_type: str, db=None) -> dict:
    """Kullanıcının gönderdiği fizik fotoğrafı/videosunu (veya antrenman formu videosunu)
    analiz eder. Maksimum hipertrofi hedefine yönelik: fizik/form değerlendirmesi +
    antrenman, beslenme ve günlük yaşam tavsiyeleri üretir.

    Dönen dict:
    - report: kullanıcıya gösterilecek tam rapor (Jarvis tonunda)
    - memory_summary: UserMemory'e kaydedilecek kısa özet (kalıcı hafıza)
    - training_instruction: modify_workout_program'a beslenebilecek somut talimat (veya None)
    - nutrition_instruction: modify_meal_plan'a beslenebilecek somut talimat (veya None)
    """
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        system_instruction = build_system_prompt(db)
        model = genai.GenerativeModel(model_name=MODEL_NAME, system_instruction=system_instruction)

        media_part = {"mime_type": mime_type, "data": media_bytes}
        prompt = """
Kullanıcı sana bir fizik fotoğrafı/videosu ya da bir antrenman formu videosu gönderdi.
Amaç: MAKSİMUM HİPERTROFİ (kas kütlesi artışı) hedefine yönelik elit seviyede bir
değerlendirme yapmak. Gördüğün şeye göre aşağıdakileri uygula:

- Eğer bu bir FİZİK fotoğrafı/videosuysa: hangi kas gruplarının göreceli olarak güçlü,
  hangilerinin geride kaldığını (lagging muscle group) değerlendir. Yaklaşık vücut yağ
  oranı ve genel simetri/duruş hakkında yorum yap.
- Eğer bu bir HAREKET/SET videosuysa: form hatalarını (eklem açısı, hareket aralığı,
  tempo, telafi hareketleri) tespit et, sakatlanma riskini belirt.

SADECE aşağıdaki JSON formatında yanıt ver, başka hiçbir şey yazma:

{
  "report": "Kullanıcıya 'efendim' diye hitap eden, dürüst ama motive edici, DETAYLI bir
    değerlendirme. Şunları İÇERMELİ: (1) Fizik/form gözlemleri, (2) hipertrofi için hangi
    kas grubuna/harekete öncelik vermesi gerektiği, (3) beslenme açısından dikkat etmesi
    gereken nokta (kalori/protein yeterli mi, vücut yağ oranına göre bulk/cut/recomp önerisi),
    (4) günlük yaşam tavsiyesi (uyku, toparlanma, stres yönetimi - hipertrofiyi doğrudan
    etkileyen faktörler). Madde madde değil, akıcı ama net bir metin olsun.",
  "memory_summary": "2-4 cümlelik, ileride hatırlanacak özet (örn: 'kullanıcının sırt
    kasları göğüse göre geride, bacak antrenmanı formunda diz içe kapanma var, X tarihinde
    tahmini %Y vücut yağı gözlemlendi').",
  "training_instruction": "Eğer analiz SOMUT bir program değişikliği gerektiriyorsa
    (örn. 'sırt hacmini artır, haftada bir gün daha ekle', 'squat formu düzeltilene kadar
    ağırlığı düşür') bunu tek cümlelik net bir talimat olarak yaz. Gerekmiyorsa null yap.",
  "nutrition_instruction": "Eğer analiz SOMUT bir beslenme değişikliği gerektiriyorsa
    (örn. 'vücut yağı düşük görünüyor, kaloriyi artırıp temiz bulk yap', 'yağlanma var,
    kaloriyi hafif kıs') bunu tek cümlelik net bir talimat olarak yaz. Gerekmiyorsa null yap."
}
"""
        response = model.generate_content(
            [media_part, prompt],
            generation_config={"response_mime_type": "application/json", "temperature": 0.4},
        )
        result = json.loads(response.text)

        if result.get("memory_summary"):
            crud.create_memory(db, category="physique_analysis", content=result["memory_summary"])

        return result
    except Exception as e:
        logger.error(f"[AI_CORE] Fizik/form analizi hatası: {e}")
        return {
            "report": "Medyanı analiz ederken bir sorun oluştu efendim, tekrar dener misin?",
            "memory_summary": None,
            "training_instruction": None,
            "nutrition_instruction": None,
        }
    finally:
        if own_session:
            db.close()


def analyze_photo(media_bytes: bytes, mime_type: str, db=None) -> dict:
    """Telegram'a atılan bir FOTOĞRAFIN yemek mi yoksa fizik/vücut fotoğrafı mı olduğunu
    tek bir Gemini vision çağrısında ayırt edip uygun analizi yapar. Video için kullanılmaz
    (video her zaman form/fizik kabul edilir - bkz. analyze_physique_media).

    Dönen dict:
    - photo_type: "food" | "physique" | "unclear"
    - food alanları (photo_type=="food" ise): meal_name, description, calories, protein,
      carbs, fats, confidence ("high"|"medium"|"low")
    - physique alanları (photo_type=="physique" ise): report, memory_summary,
      training_instruction, nutrition_instruction (analyze_physique_media ile aynı şema)
    """
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        system_instruction = build_system_prompt(db)
        model = genai.GenerativeModel(model_name=MODEL_NAME, system_instruction=system_instruction)

        media_part = {"mime_type": mime_type, "data": media_bytes}
        prompt = """
Bu fotoğrafta ne görüyorsun? Önce türünü belirle, sonra SADECE o türe uygun alanları doldur.

SADECE aşağıdaki JSON formatında yanıt ver, başka hiçbir şey yazma:

{
  "photo_type": "food" | "physique" | "unclear",

  // photo_type "food" ise (bir tabak/yemek/içecek görüyorsan) doldur, değilse null bırak:
  "food": {
    "meal_name": "Kısa isim (örn. 'Öğle Yemeği')",
    "description": "Gördüğün yemeği malzeme/miktar tahminiyle tarif et (örn. '150g tavuk göğsü,
      180g pirinç, yeşillik salata')",
    "calories": <sayı>, "protein": <sayı>, "carbs": <sayı>, "fats": <sayı>,
    "confidence": "high" | "medium" | "low"  // porsiyon/malzeme belirsizse "low" yaz
  } veya null,

  // photo_type "physique" ise (bir insan vücudu/fizik pozu görüyorsan) doldur, değilse null:
  "physique": {
    "report": "Kullanıcıya 'efendim' diye hitap eden, MAKSİMUM HİPERTROFİ hedefine yönelik
      DETAYLI değerlendirme: (1) hangi kas grupları güçlü/geride, yaklaşık vücut yağ oranı,
      (2) hipertrofi için öncelik, (3) beslenme yönlendirmesi (bulk/cut/recomp), (4) günlük
      yaşam tavsiyesi (uyku/toparlanma/stres). Akıcı bir metin, madde madde değil.",
    "memory_summary": "2-4 cümlelik kalıcı hafıza özeti.",
    "training_instruction": "Somut program değişikliği talimatı veya null.",
    "nutrition_instruction": "Somut beslenme değişikliği talimatı veya null."
  } veya null,

  // photo_type "unclear" ise (ne yemek ne fizik - başka bir şey): ikisi de null.
  "clarify_message": "photo_type 'unclear' ise kullanıcıya bunun ne olduğunu soran kısa,
    dostane bir mesaj. Diğer durumlarda null."
}
"""
        response = model.generate_content(
            [media_part, prompt],
            generation_config={"response_mime_type": "application/json", "temperature": 0.3},
        )
        result = json.loads(response.text)

        photo_type = result.get("photo_type")
        if photo_type == "food" and result.get("food"):
            food = result["food"]
            crud.create_nutrition_log(db, schemas.NutritionLogCreate(
                meal_name=food.get("meal_name", "Öğün"),
                ingredients=food.get("description", ""),
                calories=_safe_float(food.get("calories")),
                protein=_safe_float(food.get("protein")),
                carbs=_safe_float(food.get("carbs")),
                fats=_safe_float(food.get("fats")),
            ))
        elif photo_type == "physique" and result.get("physique"):
            if result["physique"].get("memory_summary"):
                crud.create_memory(db, category="physique_analysis", content=result["physique"]["memory_summary"])

        return result
    except Exception as e:
        logger.error(f"[AI_CORE] Fotoğraf analizi hatası: {e}")
        return {
            "photo_type": "unclear",
            "clarify_message": "Fotoğrafı analiz ederken bir sorun oluştu efendim, tekrar dener misin?",
        }
    finally:
        if own_session:
            db.close()


def calculate_macro_targets(age, height, weight, goal, activity_level="moderate"):
    """Profil verilerinden günlük kalori ve makro hedeflerini hesaplar (Mifflin-St Jeor)."""
    if not all([age, height, weight]):
        return {"daily_calorie_target": 2200, "daily_protein_target": 140,
                "daily_carb_target": 220, "daily_fat_target": 70}

    bmr = 10 * weight + 6.25 * height - 5 * age + 5
    multipliers = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725}
    act = (activity_level or "moderate").lower()
    tdee = bmr * multipliers.get(act, 1.55)

    goal_lower = (goal or "").lower()
    if any(w in goal_lower for w in ["yağ", "cut", "kilo ver", "zayıf", "defin"]):
        calories = tdee * 0.85
        protein = weight * 2.2
    elif any(w in goal_lower for w in ["kilo al", "bulk", "kas", "hipertrofi", "kütlesi"]):
        calories = tdee * 1.10
        protein = weight * 2.0
    else:
        calories = tdee
        protein = weight * 1.8

    fat = calories * 0.25 / 9
    carbs = (calories - protein * 4 - fat * 9) / 4
    return {
        "daily_calorie_target": round(calories),
        "daily_protein_target": round(protein),
        "daily_carb_target": round(max(carbs, 0)),
        "daily_fat_target": round(fat),
    }


def complete_onboarding(
    db,
    video_bytes: bytes = None,
    video_mime: str = "video/mp4",
    nutrition_transcript: str = "",
    training_transcript: str = "",
    lifestyle_transcript: str = "",
    age: int = None,
    height: float = None,
    weight: float = None,
    goal: str = "",
):
    """Video + ses kayıtları + temel bilgilerden kişiselleştirilmiş profil oluşturur,
    makro hedeflerini hesaplar ve beslenme/antrenman programı üretir."""
    physique_analysis = None
    if video_bytes:
        physique_analysis = analyze_physique_media(video_bytes, video_mime, db)

    system_instruction = BASE_PERSONA
    model = genai.GenerativeModel(model_name=MODEL_NAME, system_instruction=system_instruction)

    physique_block = ""
    if physique_analysis and physique_analysis.get("memory_summary"):
        physique_block = f"\nVÜCUT VİDEO ANALİZİ:\n{physique_analysis['memory_summary']}\n"

    prompt = f"""
Kullanıcının onboarding (ilk kurulum) verilerini analiz et ve profil alanlarını doldur.

{physique_block}
GÜNCEL BESLENME (ses kaydı transkripti):
{nutrition_transcript or 'belirtilmedi'}

GÜNCEL ANTRENMAN (ses kaydı transkripti):
{training_transcript or 'belirtilmedi'}

GÜNLÜK YAŞAM (ses kaydı transkripti):
{lifestyle_transcript or 'belirtilmedi'}

TEMEL BİLGİLER (kullanıcının girdiği):
- Yaş: {age}, Boy: {height} cm, Kilo: {weight} kg
- Hedef: {goal}

SADECE aşağıdaki JSON formatında yanıt ver:

{{
  "goal": "kısa hedef özeti (bulk/cut/recomp/maintain veya Türkçe açıklama)",
  "target_physique": "hedeflediği fiziksel görünüm (1-2 cümle)",
  "experience_months": <tahmini antrenman deneyimi ay cinsinden, sayı>,
  "focus_muscle_group": "öncelikli kas grubu veya 'genel/dengeli'",
  "activity_level": "sedentary|light|moderate|active",
  "dietary_notes": "beslenme tercihleri, kısıtlamalar, alerjiler - ses kaydından çıkar",
  "schedule_notes": "uyku, iş yoğunluğu, antrenman zamanı tercihi - ses kaydından çıkar",
  "injury_notes": "sakatlık/kısıtlama varsa, yoksa boş string",
  "onboarding_summary": "2-3 cümlelik Jarvis tonunda kullanıcı özeti (hafızaya kaydedilecek)"
}}
"""
    try:
        response = model.generate_content(
            prompt, generation_config={"response_mime_type": "application/json", "temperature": 0.4}
        )
        parsed = json.loads(response.text)
    except Exception as e:
        logger.error(f"[AI_CORE] Onboarding sentez hatası: {e}")
        parsed = {
            "goal": goal or "recomp",
            "dietary_notes": nutrition_transcript[:500] if nutrition_transcript else "",
            "schedule_notes": lifestyle_transcript[:500] if lifestyle_transcript else "",
            "activity_level": "moderate",
            "experience_months": 0,
            "focus_muscle_group": "",
            "target_physique": "",
            "injury_notes": "",
            "onboarding_summary": "Profil oluşturuldu.",
        }

    macros = calculate_macro_targets(
        age, height, weight,
        parsed.get("goal") or goal,
        parsed.get("activity_level", "moderate"),
    )

    profile_data = {
        "age": age,
        "height": height,
        "current_weight": weight,
        "goal": parsed.get("goal") or goal,
        "target_physique": parsed.get("target_physique", ""),
        "experience_months": parsed.get("experience_months") or 0,
        "focus_muscle_group": parsed.get("focus_muscle_group", ""),
        "activity_level": parsed.get("activity_level", "moderate"),
        "dietary_notes": parsed.get("dietary_notes", ""),
        "schedule_notes": parsed.get("schedule_notes", ""),
        "injury_notes": parsed.get("injury_notes", ""),
        "onboarding_completed": True,
        **macros,
    }
    crud.update_profile(db, profile_data)

    summary_parts = []
    if nutrition_transcript:
        crud.create_memory(db, category="onboarding_nutrition", content=nutrition_transcript[:2000])
        summary_parts.append(f"Beslenme: {nutrition_transcript[:200]}")
    if training_transcript:
        crud.create_memory(db, category="onboarding_training", content=training_transcript[:2000])
        summary_parts.append(f"Antrenman: {training_transcript[:200]}")
    if lifestyle_transcript:
        crud.create_memory(db, category="onboarding_lifestyle", content=lifestyle_transcript[:2000])
        summary_parts.append(f"Yaşam: {lifestyle_transcript[:200]}")

    if parsed.get("onboarding_summary"):
        crud.create_memory(db, category="onboarding", content=parsed["onboarding_summary"])

    training_instruction = None
    nutrition_instruction = None
    if physique_analysis:
        training_instruction = physique_analysis.get("training_instruction")
        nutrition_instruction = physique_analysis.get("nutrition_instruction")

    meal_plan = generate_meal_plan(db, user_instruction=nutrition_instruction)
    workout_programs = generate_workout_program(db, user_instruction=training_instruction)

    return {
        "profile": profile_data,
        "physique_report": physique_analysis.get("report") if physique_analysis else None,
        "onboarding_summary": parsed.get("onboarding_summary"),
        "meal_plan_count": len(meal_plan) if meal_plan else 0,
        "workout_days": len(workout_programs) if workout_programs else 0,
    }


def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    """Telegram'dan gelen bir sesli mesajı (voice note) Türkçe metne çevirir.
    Bu fonksiyon SADECE transkripsiyon yapar - anlamlandırma/kaydetme işini yapmaz.
    Çıkan metin, mevcut process_message() fonksiyonuna gönderilerek metinle aynı
    intent sistemi (log_food, log_workout, query_history, sohbet vb.) üzerinden işlenir -
    böylece ses ve metin girişleri için ayrı iki mantık yazmak zorunda kalmıyoruz."""
    try:
        model = genai.GenerativeModel(model_name=MODEL_NAME)
        audio_part = {"mime_type": mime_type, "data": audio_bytes}
        prompt = (
            "Bu ses kaydını Türkçe olarak birebir metne dök. Sadece söylenen kelimeleri yaz, "
            "başka hiçbir yorum, açıklama veya noktalama düzeltmesi ekleme. Ses kaydında "
            "konuşma yoksa veya anlaşılmıyorsa sadece '[ANLAŞILAMADI]' yaz."
        )
        response = model.generate_content(
            [audio_part, prompt], generation_config={"temperature": 0.1}
        )
        return response.text.strip()
    except Exception as e:
        logger.error(f"[AI_CORE] Ses transkripsiyon hatası: {e}")
        return "[ANLAŞILAMADI]"
