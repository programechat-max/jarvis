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
import time
import tempfile
from datetime import date, timedelta

import google.generativeai as genai
from dotenv import load_dotenv

import crud
import schemas
import progression
import jarvis_brain
from database import SessionLocal

load_dotenv()
logger = logging.getLogger(__name__)

API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=API_KEY)

MODEL_NAME = "gemini-3.1-flash-lite"

BASE_PERSONA = """
Sen kullanıcının kişisel 'Jarvis' adındaki elit, sadık ve zeki fitness/sağlık asistanısın.
Iron Man filmindeki Jarvis gibi asil, sadık, hafif nüktedan ve tamamen kullanıcı odaklısın.
Kullanıcıya her zaman "efendim" diye hitap et. Kuru, robotik onay cümleleri kurma;
onunla gerçek bir koç gibi, doğal ve samimi konuş. Yanlış bir bilgi varsa nazikçe düzelt.
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
        memories = crud.get_recent_memories(db)

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
            durable = [m for m in memories if m.category != "analysis"]
            analyses = [m for m in memories if m.category == "analysis"]
            mem_sections = []
            if durable:
                mem_sections.append(
                    "Kalıcı tercih/not/içgörüler:\n"
                    + "\n".join(f"- ({m.category}) {m.content}" for m in durable)
                )
            if analyses:
                mem_sections.append(
                    "En son haftalık analiz özeti:\n"
                    + "\n".join(f"- {m.content}" for m in analyses)
                )
            memory_block = (
                "\nJARVIS'İN KULLANICI HAKKINDA BİRİKTİRDİĞİ HAFIZA "
                "(bunlar geçmiş sohbetlerden biriken GERÇEK bilgiler, yok sayma):\n"
                + "\n\n".join(mem_sections) + "\n"
            )
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
GÖREVİN: Kullanıcının mesajını analiz et ve SADECE aşağıdaki JSON formatında yanıt dön.
JSON dışında hiçbir şey yazma.

{
  "intent": "log_food" | "complete_all_meals" | "log_workout" | "log_weight" | "remember" | "forget" | "query_history" | "modify_meal_plan" | "delete_meal_plan" | "delete_food_log" | "modify_workout_program" | "delete_workout_program" | "explain_why" | "coaching_advice" | "daily_checkin" | "compare_period" | "chat",
  "data": {
    // log_food ise: "meal_name", "description", "calories", "protein", "carbs", "fats", "matched_plan_meal"
    //   KURAL 1 - Kullanıcı NE YEDİĞİNİ somut olarak tarif ettiyse (malzeme/miktar belirtmiş,
    //     örn. "3 yumurta yedim", "150g tavuk ve pirinç yedim"): description'a bunu yaz,
    //     calories/protein/carbs/fats'ı bu tarife göre rasyonel hesapla. matched_plan_meal: null.
    //   KURAL 2 - Kullanıcı SADECE "planımdaki kahvaltıyı/öğle yemeğimi/X öğününü yedim" gibi
    //     BELİRSİZ bir ifade kullandıysa (ne yediğini TARİF ETMEDEN, sadece plan öğününe atıfla):
    //     calories/protein/carbs/fats alanlarına 0 yaz (bunlar KULLANILMAYACAK, kod gerçek plan
    //     verisini DB'den çekip kullanacak) ve matched_plan_meal alanına o öğünün planındaki
    //     TAM meal_name'ini yaz (örn. "Kahvaltı", "Öğle Yemeği") - SİSTEM PROMPT'taki güncel
    //     BESLENME PLANI bölümünden hangi öğün olduğunu belirle. Eşleşen öğün yoksa null yaz ve
    //     jarvis_reply'de kullanıcıya ne yediğini sorman GEREKİR, kaydetme.
    //   ASLA sayısal alanlara rastgele/uydurma değer yazıp matched_plan_meal'i de null bırakma -
    //     ya somut tarife dayalı gerçek hesap yap, ya da plana yönlendir, ikisi de değilse SOR.

    // complete_all_meals ise: veri gerekmez, boş obje {} yeterli.
    //   BU INTENT'İ KULLAN: kullanıcı GÜNÜN PLANINDAKİ BÜTÜN öğünleri yediğini/tamamladığını
    //   TEK BİR CÜMLEYLE, öğünleri tek tek saymadan bildiriyorsa (örn: "tüm öğünlerimi
    //   tamamladım", "bugün planımdaki her şeyi yedim", "günü planıma birebir uydum",
    //   "bugünkü menüyü eksiksiz bitirdim"). log_food'dan FARKI: log_food tek bir öğüne
    //   (örn. sadece kahvaltı) atıfla kullanılır, complete_all_meals ise "TÜMÜ/HEPSİ/BÜTÜN
    //   GÜN" gibi bir bütünlüğe atıfla kullanılır. jarvis_reply'i BOŞ BIRAK ("") - kod
    //   plandaki her öğünü tek tek DB'den çekip kaydedecek ve gerçek özeti kendisi yazacak.

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

    // log_weight ise: "weight", "waist", "chest", "arm", "sleep_hours"
    // remember ise: "category" ("preference"|"note"), "content"
    //   (kullanıcı kalıcı bir tercih, alışkanlık veya yaşam tarzı bilgisi paylaştıysa kullan,
    //    örn: "balık yemem", "akşamları geç yatıyorum", "dizimde eski bir sakatlık var")
    //   Eğer bu bilgi, SİSTEM PROMPT'taki "JARVIS'İN KULLANICI HAKKINDA BİRİKTİRDİĞİ HAFIZA"
    //   bölümünde zaten var olan bir kaydı GÜNCELLİYORSA/DÜZELTİYORSA (örn. eskiden "dizimde
    //   sakatlık var" yazıyordu, şimdi "dizim artık iyi") content'e YENİ HALİNİ yaz - eski
    //   bilgi otomatik olarak devre dışı bırakılacak, sen ikisini birden yazmaya çalışma.
    // forget ise: "content" (unutulacak/artık geçersiz olan bilginin kısa özeti)
    //   BU INTENT'İ KULLAN: kullanıcı AÇIKÇA "bunu unut", "artık öyle değil, kaydı sil",
    //   "o bilgi yanlıştı/eskidi, çıkar" gibi HAFIZADAKİ bir kaydı iptal etmek istediğini
    //   belirtiyorsa. content alanına, hafızadaki hangi kaydın kastedildiğini SİSTEM
    //   PROMPT'taki hafıza bölümüne bakarak olabildiğince aynen yaz (eşleştirme buna göre
    //   yapılacak).
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

    // explain_why ise: "topic" (kullanıcının "neden" sorduğu konu — örn. "bench seçimi", "protein hedefi", "deload")
    //   BU INTENT'İ KULLAN: kullanıcı bir karar/program/hareket/hedef hakkında "neden", "niçin",
    //   "neden bunu önerdin/seçtin" diye soruyorsa. jarvis_reply'i BOŞ BIRAK ("") — zenginleştirme katmanı dolduracak.

    // coaching_advice ise: "topic" (genel koçluk konusu — beslenme, antrenman, toparlanma, motivasyon)
    //   BU INTENT'İ KULLAN: kullanıcı genel tavsiye/öneri istiyorsa ("ne yapmalıyım", "bugün ne önerirsin",
    //   "nasıl ilerlerim"). jarvis_reply'i BOŞ BIRAK ("").

    // daily_checkin ise: "mood", "energy", "sleep_quality", "soreness" (her biri 1-5 int, belirtilmemişse null),
    //   "notes" (serbest metin duygu durumu)
    //   BU INTENT'İ KULLAN: kullanıcı bugün nasıl hissettiğini/enerjisini/uykusunu raporluyorsa
    //   ("bugün çok yorgunum", "iyi uyudum", "kaslarım ağrıyor", "kendimi harika hissediyorum").
    //   jarvis_reply'i BOŞ BIRAK ("") — kod hazırlık skorunu hesaplayacak.

    // compare_period ise: "days" (int, varsayılan 7)
    //   BU INTENT'İ KULLAN: kullanıcı dönem karşılaştırması istiyorsa ("bu hafta vs geçen hafta",
    //   "son 7 günde nasıl gidiyorum", "gelişimim nasıl"). jarvis_reply'i BOŞ BIRAK ("").
  },
  "jarvis_reply": "Kullanıcıya Jarvis tonunda, kişiselleştirilmiş, kısa ve motive edici yanıt."
}

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


def process_message(user_message: str, db=None, session_id: str = "default") -> dict:
    """Tek giriş noktası: mesajı analiz eder, intent'e göre veritabanına yazar
    ve kullanıcıya verilecek yanıtı döndürür. jarvis_brain katmanı ile zenginleştirilir."""
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        crud.save_chat_message(db, "user", user_message, session_id=session_id)

        system_instruction = jarvis_brain.build_enhanced_system_prompt(
            db, user_message, BASE_PERSONA, INTENT_INSTRUCTIONS
        )
        model = genai.GenerativeModel(model_name=MODEL_NAME, system_instruction=system_instruction)

        response = model.generate_content(
            user_message,
            generation_config={"response_mime_type": "application/json", "temperature": 0.4},
        )
        result = json.loads(response.text)
        intent = result.get("intent")
        data = result.get("data", {}) or {}

        if intent == "log_food":
            import schemas
            matched_meal_name = data.get("matched_plan_meal")

            if matched_meal_name:
                # Kullanıcı "planımdaki X'i yedim" dedi - AI'nin uydurduğu değil,
                # veritabanındaki GERÇEK plan verisini kullan.
                plan_items = crud.get_meal_plan(db)
                matched = next(
                    (p for p in plan_items if p.meal_name.strip().lower() == matched_meal_name.strip().lower()),
                    None,
                )
                if matched:
                    crud.create_nutrition_log(db, schemas.NutritionLogCreate(
                        meal_name=matched.meal_name,
                        ingredients=matched.description,
                        calories=matched.calories,
                        protein=matched.protein,
                        carbs=matched.carbs,
                        fats=matched.fats,
                    ))
                    result["jarvis_reply"] = (
                        f"✅ {matched.meal_name} kaydedildi efendim ({matched.calories:.0f} kcal, "
                        f"{matched.protein:.0f}g protein) - plandaki haliyle."
                    )
                    result["_food_reply_is_final"] = True
                else:
                    # AI plan içinde eşleşme bulamadı ama yine de matched_plan_meal döndürmüş -
                    # veri uydurmak yerine kullanıcıya sor.
                    result["jarvis_reply"] = (
                        "Planında bu isimde bir öğün bulamadım efendim. Ne yediğini biraz "
                        "tarif eder misin, öyle kaydedeyim?"
                    )
                    result["intent"] = "chat"
            else:
                calories = _safe_float(data.get("calories"), default=None)
                # AI hem plana eşlemedi hem de somut bir kalori hesaplamadıysa (description boş/
                # belirsiz), rastgele 0 kaydetmek yerine kullanıcıya sor.
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
        elif intent == "complete_all_meals":
            import schemas
            plan_items = crud.get_meal_plan(db)
            if not plan_items:
                result["jarvis_reply"] = (
                    "Şu an kayıtlı bir beslenme planın yok efendim, o yüzden 'tümünü tamamladım' "
                    "diyebileceğim bir öğün listesi bulamadım. Önce /beslenme ile bir plan "
                    "oluşturalım, ya da ne yediğini tek tek anlat, öyle kaydedeyim."
                )
            else:
                already_logged = {
                    m.meal_name.strip().lower() for m in crud.get_nutrition_logs_by_date(db, date.today())
                }
                newly_logged = []
                for item in plan_items:
                    if item.meal_name.strip().lower() in already_logged:
                        continue
                    crud.create_nutrition_log(db, schemas.NutritionLogCreate(
                        meal_name=item.meal_name,
                        ingredients=item.description,
                        calories=item.calories,
                        protein=item.protein,
                        carbs=item.carbs,
                        fats=item.fats,
                    ))
                    newly_logged.append(item)

                if not newly_logged:
                    result["jarvis_reply"] = (
                        "Zaten planındaki tüm öğünleri bugün için ayrı ayrı kaydetmiştin efendim, "
                        "tekrar eklemedim - günün tamamlanmış görünüyor."
                    )
                else:
                    total_cal = sum(i.calories for i in newly_logged)
                    total_prot = sum(i.protein for i in newly_logged)
                    meal_names = ", ".join(i.meal_name for i in newly_logged)
                    skipped_note = (
                        f" ({len(plan_items) - len(newly_logged)} tanesini zaten önceden kaydetmiştin, atladım.)"
                        if len(newly_logged) < len(plan_items) else ""
                    )
                    result["jarvis_reply"] = (
                        f"✅ Planındaki tüm öğünleri tamamladım olarak kaydettim efendim: {meal_names} "
                        f"— toplam {total_cal:.0f} kcal, {total_prot:.0f}g protein.{skipped_note}"
                    )
                result["_food_reply_is_final"] = True
        elif intent == "forget":
            target_content = (data.get("content") or "").strip()
            removed = crud.forget_memory(db, target_content) if target_content else None
            if removed:
                result["jarvis_reply"] = f"🧠 Anladım efendim, bunu hafızamdan çıkardım: \"{removed.content}\""
            else:
                result["jarvis_reply"] = (
                    "Hafızamda buna tam karşılık gelen bir kayıt bulamadım efendim - "
                    "biraz daha net söyler misin, neyi unutmamı istiyorsun?"
                )
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
            crud.create_memory(
                db,
                category=data.get("category", "preference"),
                content=data.get("content", user_message),
                importance=7,
            )
        elif intent == "explain_why":
            result["_force_enrich"] = True
            result["jarvis_reply"] = ""
        elif intent == "coaching_advice":
            result["_force_enrich"] = True
            result["jarvis_reply"] = ""
        elif intent == "daily_checkin":
            mood = _safe_int(data.get("mood"), default=None) or 3
            energy = _safe_int(data.get("energy"), default=None) or 3
            sleep_q = _safe_int(data.get("sleep_quality"), default=None) or 3
            soreness = _safe_int(data.get("soreness"), default=None) or 2
            notes = data.get("notes") or user_message
            checkin_result = jarvis_brain.process_checkin(db, mood, energy, sleep_q, soreness, notes)
            result["jarvis_reply"] = checkin_result["jarvis_reply"]
            result["data"]["checkin"] = checkin_result["checkin"]
            result["data"]["training_advice"] = checkin_result["training_advice"]
            result["_skip_enrich"] = True
        elif intent == "compare_period":
            days = _safe_int(data.get("days"), default=7) or 7
            comparison = jarvis_brain.handle_compare_period(db, days=days)
            result["jarvis_reply"] = comparison
            result["_force_enrich"] = True
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

        # PR kutlaması — log_workout sonrası
        if intent == "log_workout" and result.get("_new_prs"):
            pr_msgs = []
            for ex_name, weight, prev in result["_new_prs"]:
                if prev > 0:
                    pr_msgs.append(f"🏆 YENİ REKOR: {ex_name} — {weight}kg (önceki: {prev}kg)!")
                else:
                    pr_msgs.append(f"🏆 İlk kayıt: {ex_name} — {weight}kg!")
            if pr_msgs and not result.get("_food_reply_is_final"):
                base = (result.get("jarvis_reply") or "").strip()
                result["jarvis_reply"] = (base + "\n" + "\n".join(pr_msgs)).strip() if base else "\n".join(pr_msgs)

        # Koçluk zenginleştirmesi — ham API yanıtını güçlendirir
        result = jarvis_brain.enrich_reply_with_coaching(db, user_message, result)

        # Otomatik hafıza madenciliği
        jarvis_brain.extract_implicit_memories(db, user_message, result.get("jarvis_reply", ""))

        reply_text = result.get("jarvis_reply", "")
        crud.save_chat_message(db, "jarvis", reply_text, intent=intent, session_id=session_id)

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

HAREKET SEÇİMİ - BU PROGRAM MAKSİMUM HİPERTROFİ (kas büyümesi) İÇİN TASARLANACAK, rastgele
"bilinen/klasik" hareketleri sıralama. Güncel direnç antrenmanı bilimine (mekanik gerilim,
gerilmiş pozisyonda yük = "stretch-mediated hypertrophy", tam hareket açıklığı, kas başına
uyarı/yorgunluk oranı) göre karar ver:
- HER kas grubu için, o kası GERİLMİŞ/UZAMIŞ pozisyonda da yükleyen en az bir hareket bulundur.
  Örnek: biceps için SADECE ayakta klasik barbell curl yazıp geçme - bunun yanına/yerine omuz
  arkada olacak şekilde geren bir hareket ekle (örn. incline dumbbell curl, spider curl, veya
  kabloyla vücut arkasında yapılan curl varyasyonu); triceps için kolun baş üstünde olduğu bir
  hareket (örn. overhead extension) ekle - düz pushdown TEK BAŞINA yeterli değil; göğüs için
  yatık/eğimli açıları ve alt kısmı ihmal etme; sırt için hem çekme (rowing, dikey açıklık)
  hem de lat açılımı (üstten çekiş) olsun; bacak için hem diz baskın (squat/leg press tipi)
  hem kalça baskın (hip hinge - RDL, hip thrust) hareket bulunsun.
- Her günde ÖNCE çok eklemli/bileşik (compound) hareketler, SONRA izolasyon hareketleri gelsin -
  yorgunluk biriktiği için en çok kas kütlesi/yük kaldıran hareketler antrenmanın başında olmalı.
- Ağır bileşik hareketler için 5-10, orta/hipertrofi odaklı ana hareketler için 8-12, izolasyon
  ve uzun kaslar (biceps, triceps, omuz yan baş, karın, baldır) için 10-20 tekrar aralığı kullan -
  tek tip "8-12" ile her hareketi doldurma.
- Aynı hareketi/paterni gereksiz tekrar etme (örn. bir günde 3 farklı düz bench varyasyonu değil,
  açı/ekipman çeşitliliği ver: barbell, dumbbell, kablo, makine karışık kullan) - bu hem farklı
  açılardan uyarı sağlar hem eklem üzerindeki tekrarlayan yükü azaltır.
- Deneyimi az olan kullanıcılar için (örn. {profile.experience_months or 0} ay < 6) teknik açıdan
  daha kolay/stabil hareketleri (makine, dumbbell) öne çıkar; ileri seviye kullanıcılar için
  serbest ağırlık ve tek taraflı (unilateral) hareketleri de programa dahil et.
- Odak bölge belirtilmişse ({profile.focus_muscle_group or 'belirtilmedi'}), o kas grubuna
  haftalık daha fazla set/daha sık frekans ayır, ama hiçbir ana kas grubunu haftada en az bir
  kez çalıştırmadan bırakma (dengesiz gelişim/sakatlık riski oluşturma).

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


def _upload_video_to_gemini(media_bytes: bytes, mime_type: str):
    """Videoyu inline (doğrudan base64 bytes) yerine Gemini'nin FILES API'sine yükler.
    NEDEN GEREKLİ: inline gönderim sadece birkaç MB'a kadar güvenilir çalışır - onboarding'de
    çekilen 15-20 saniyelik bir vücut videosu bunu kolayca aşıyor. Aşıldığında istek ya
    Gemini tarafında reddediliyor ya da FastAPI sürecinde base64'e çevrilirken (boyut ~%33
    büyüyor) çok uzun sürüp tarayıcıda 'Load failed' / 'Failed to fetch' ile sonuçlanan bir
    bağlantı kopmasına yol açıyor. Files API büyük dosyaları güvenilir şekilde kabul eder ve
    arkada asenkron işler; biz de burada 'ACTIVE' duruma geçmesini bekliyoruz."""
    suffix = ".webm" if "webm" in mime_type else ".mp4"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(media_bytes)
            tmp_path = tmp.name

        uploaded = genai.upload_file(path=tmp_path, mime_type=mime_type)
        waited = 0
        while uploaded.state.name == "PROCESSING" and waited < 120:
            time.sleep(2)
            waited += 2
            uploaded = genai.get_file(uploaded.name)

        if uploaded.state.name != "ACTIVE":
            raise RuntimeError(f"Gemini video dosyası işlenemedi (durum: {uploaded.state.name})")
        return uploaded
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


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
    uploaded_file = None
    try:
        system_instruction = build_system_prompt(db)
        model = genai.GenerativeModel(model_name=MODEL_NAME, system_instruction=system_instruction)

        # 15MB üzerindeki ya da video/* olan her medya önce Files API'yi dener (bkz. yukarı
        # not). Bazı google-generativeai SDK sürümlerinde Files API, sade bir API key ile
        # discovery tabanlı bir alt istemci kullanıyor ve bu ayrı bir yetkilendirme kontrolü
        # gerektirebiliyor ("API key not valid" + $discovery/rest URL'i bunun belirtisidir -
        # generateContent çağrıları farklı bir yol izlediği için ondan etkilenmez, örn.
        # Telegram tarafı bu yüzden sorunsuz çalışabilir). Bu durumda kullanıcıyı hatayla baş
        # başa bırakmak yerine, video zaten kayıt sırasında küçük tutulduğu (~20sn/1.2Mbps,
        # birkaç MB) için inline gönderime düşüyoruz.
        MAX_INLINE_BYTES = 15 * 1024 * 1024
        is_video = mime_type.startswith("video/")
        media_part = None
        if is_video or len(media_bytes) > MAX_INLINE_BYTES:
            try:
                uploaded_file = _upload_video_to_gemini(media_bytes, mime_type)
                media_part = uploaded_file
            except Exception as upload_err:
                logger.warning(f"[AI_CORE] Files API başarısız, inline gönderime düşülüyor: {upload_err}")
                if len(media_bytes) > MAX_INLINE_BYTES:
                    raise RuntimeError(
                        "Video Files API ile yüklenemedi ve inline gönderim için çok büyük "
                        f"({len(media_bytes) / (1024*1024):.1f}MB > {MAX_INLINE_BYTES // (1024*1024)}MB). "
                        "google-generativeai paketini güncelleyip tekrar dener misin?"
                    ) from upload_err
        if media_part is None:
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
            "report": "Medyanı analiz ederken bir sorun oluştu efendim, tekrar dener misin? "
                      "(Video çok uzunsa 10-15 saniyeye indirip tekrar dene.)",
            "memory_summary": None,
            "training_instruction": None,
            "nutrition_instruction": None,
        }
    finally:
        if uploaded_file is not None:
            try:
                genai.delete_file(uploaded_file.name)
            except Exception as cleanup_err:
                logger.warning(f"[AI_CORE] Gemini'deki geçici video dosyası silinemedi: {cleanup_err}")
        if own_session:
            db.close()


def analyze_photo(media_bytes: bytes, mime_type: str, db=None, save: bool = True) -> dict:
    """Telegram'a atılan bir FOTOĞRAFIN yemek mi yoksa fizik/vücut fotoğrafı mı olduğunu
    tek bir Gemini vision çağrısında ayırt edip uygun analizi yapar. Video için kullanılmaz
    (video her zaman form/fizik kabul edilir - bkz. analyze_physique_media).

    save=False verilirse analiz sonucu döner ama veritabanına YAZMAZ — web arayüzünde
    kullanıcının önce makroları onaylaması için kullanılır.

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
        if save and photo_type == "food" and result.get("food"):
            food = result["food"]
            crud.create_nutrition_log(db, schemas.NutritionLogCreate(
                meal_name=food.get("meal_name", "Öğün"),
                ingredients=food.get("description", ""),
                calories=_safe_float(food.get("calories")),
                protein=_safe_float(food.get("protein")),
                carbs=_safe_float(food.get("carbs")),
                fats=_safe_float(food.get("fats")),
            ))
        elif save and photo_type == "physique" and result.get("physique"):
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


def extract_profile_from_transcript(transcript: str, db=None) -> dict:
    """Onboarding sırasında kullanıcının sesli olarak anlattığı 'güncel beslenmem,
    antrenmanım, günlük rutinim, hedefim' konuşmasının METNİNİ (transcribe_audio çıktısı)
    yapılandırılmış profil alanlarına ve kalıcı hafızaya dönüştürür. Böylece kullanıcı
    formda doldurmadığı ama sesli anlattığı her şey (diyet kısıtlamaları, uyku düzeni,
    sakatlıklar, gerçek hedefi) otomatik olarak UserProfile + UserMemory'e işlenir ve
    bundan sonra üretilecek program/beslenme planı bunu hesaba katar.

    Dönen dict:
    - profile_updates: UserProfile alanlarına (varsa) yazılacak değerler
    - summary: kullanıcıya "işte anladıklarım" diye gösterilecek kısa, doğal metin
    - memory_summary: UserMemory'e kaydedilecek kalıcı özet
    """
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        model = genai.GenerativeModel(model_name=MODEL_NAME)
        prompt = f"""
Kullanıcı, profilini oluştururken kendi sesiyle güncel beslenmesini, antrenman rutinini,
günlük yaşamını ve hedeflerini anlattı. Aşağıda bu konuşmanın transkripti var:

\"\"\"{transcript}\"\"\"

Bu transkripti oku ve aşağıdaki JSON formatında, SADECE JSON olacak şekilde yanıt ver:

{{
  "profile_updates": {{
    "goal": "bulk" | "cut" | "recomp" | "maintain" | null,
    "activity_level": "sedentary" | "light" | "moderate" | "active" | null,
    "dietary_notes": "Anlatılan yeme alışkanlıkları/kısıtlamalar/alerjiler kısa özet, yoksa null",
    "schedule_notes": "Uyku saatleri, iş/okul yoğunluğu, günlük rutin kısa özet, yoksa null",
    "injury_notes": "Bahsedilen sakatlık/kısıtlama varsa kısa özet, yoksa null",
    "experience_months": <sayı, konuşmadan tahmin edilebiliyorsa, yoksa null>,
    "focus_muscle_group": "Bahsedilen öncelikli/hedef kas grubu varsa, yoksa null",
    "target_physique": "Sözel olarak tarif edilen hedef fizik varsa kısa özet, yoksa null"
  }},
  "summary": "Kullanıcıya 'efendim' diye hitap eden, 2-3 cümlelik, anladıklarını doğal bir
    dille özetleyen kısa bir mesaj (örn: 'Şu an günde 2 öğün yediğini, haftada 3 gün ağırlık
    çalıştığını ve öncelikli olarak sırtını geliştirmek istediğini anladım efendim.').",
  "memory_summary": "Jarvis'in bundan sonraki her sohbette hatırlaması gereken, 3-5 cümlelik
    kalıcı özet (güncel beslenme düzeni, antrenman rutini, günlük yaşam, gerçek hedef)."
}}

Transkriptte '[ANLAŞILAMADI]' yazıyorsa veya anlamlı bir içerik yoksa tüm profile_updates
alanlarını null yap, summary'de bunu nazikçe belirt.
"""
        response = model.generate_content(
            prompt, generation_config={"response_mime_type": "application/json", "temperature": 0.3}
        )
        result = json.loads(response.text)

        updates = {k: v for k, v in (result.get("profile_updates") or {}).items() if v not in (None, "")}
        if updates:
            crud.update_profile(db, updates)
        if result.get("memory_summary"):
            crud.create_memory(db, category="onboarding_voice", content=result["memory_summary"])

        return {
            "transcript": transcript,
            "profile_updates": updates,
            "summary": result.get("summary") or "Anlattıklarını not aldım efendim.",
        }
    except Exception as e:
        logger.error(f"[AI_CORE] Sesli onboarding profil çıkarım hatası: {e}")
        return {"transcript": transcript, "profile_updates": {}, "summary": "Anlattıklarını tam işleyemedim efendim, formdaki bilgilerle devam ediyorum."}
    finally:
        if own_session:
            db.close()
