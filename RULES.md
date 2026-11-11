# TFT Set 18 AI Coach Platform — Kodlama, Güvenlik ve Riot Uyumluluk Kuralları (RULES.md)

Bu belge, **`v2-chat-platform`** dalında geliştirilecek Django uygulaması ve mevcut [`src/`](file:///C:/Users/besir_secilmis/.gemini/antigravity/scratch/tft-meta-analyzer/src) veri motorunda uyulması zorunlu teknik kuralları ve Riot Games politikalarını tanımlar.

---

## 1. Riot Games Geliştirici Politikaları ve Production API Kuralları (KRİTİK)

1. **Eklenti (Augment) Sayısal İstatistik Yasağı:**
   * Riot Games kuralları gereği hiçbir sayfada, sohbet yanıtında, görsel kartta veya API çıktısında eklentilere (Augments) ait sayısal **Ortalama Sıra (`avg_place`)**, **Kazanma Oranı (`win_rate`)**, **İlk 4 Oranı (`top4_rate`)** veya **Seçilme Yüzdesi (`pick_rate`)** **kesinlikle gösterilemez**.
   * Eklentiler yalnızca küratörlü harf kademeleri (`S / A / B / C Tier`), aşama bilgisi (`2-1`, `3-2`, `4-2`), açıklama, taktiksel rol etiketleri (`Econ`, `Combat`, `Items`) ve önerilen sinerji kompozisyonlarıyla sunulmalıdır.
2. **Oyun İçi Otopilot Yasağı ("No Real-Time In-Game Decision Making"):**
   * Platform oyun esnasında ekranı canlı okuyan bir overlay veya anlık hamle dikte eden bir bot olarak konumlandırılamaz.
   * Tüm oyuncu maç analizleri (`apps.riot_sync`), yalnızca **tamamlanmış maçlar (`tft-match-v1`)** üzerinden **Maç Sonu Koçluk (Post-Game Reflection)** amacıyla yapılmalıdır.
3. **Yasal Uyarı (Legal Jibber Jabber) ve Doğrulama Dosyası:**
   * Sitenin alt bilgisinde (footer) Riot Games'in resmi *"isn't endorsed by Riot Games..."* yasal metni her zaman görünür olmalıdır.
   * [`docs/riot.txt`](file:///C:/Users/besir_secilmis/.gemini/antigravity/scratch/tft-meta-analyzer/docs/riot.txt) ve Django üzerindeki `/riot.txt` uç noktası (`55016fcd-fe08-40f7-bf33-18a2dbc82a60`) asla silinmemeli ve değiştirilmemelidir.

---

## 2. Django Mimari ve Kodlama Standartları

1. **`src/` Veri Motoru ile Sıfır Kod Tekrarı (DRY):**
   * CDragon veri çekme, matematiksel diff hesaplama, Team Planner kodu üretme ve RAG parçacığı oluşturma mantığı Django içinde yeniden yazılmamalı; doğrudan [`src/`](file:///C:/Users/besir_secilmis/.gemini/antigravity/scratch/tft-meta-analyzer/src) paketinden import edilmelidir.
2. **İnce Görünüm, Kalın Servis Katmanı (Thin Views, Fat Services):**
   * `views.py` dosyaları yalnızca HTTP/HTMX isteklerini karşılamalı ve şablon döndürmelidir.
   * İş mantığı (Riot API çağrıları, RAG skorlama, LLM istemi oluşturma, görsel kart eşleştirme, kota düşme) `services.py`, `llm_service.py`, `card_builder.py` ve `analyzer.py` modüllerinde yer almalıdır.
3. **Misafir + Üye Hibrit Çalışma:**
   * Siteye ilk kez giren bir kullanıcı **üye olmadan da** ana sayfadaki Chatbot'u (günlük misafir kotası dahilinde, `session_key` ile) hemen kullanabilmeli; geçmiş sohbetleri sol menüde tutulmalıdır. Kullanıcı kayıt olduğunda misafir oturumundaki sohbetler otomatik olarak yeni hesabına aktarılmalıdır.
4. **Hata Toleransı ve Yedekli AI Yanıtı:**
   * Gemini API veya Riot API zaman aşımına uğradığında ya da anahtar tanımlı olmadığında sohbet ekranı asla `500 Internal Server Error` vermemeli; `RAGChunk` veritabanındaki yerel telemetri üzerinden deterministik bir koçluk yanıtı ve görsel kompozisyon kartı döndürmelidir.

---

## 3. Arayüz (UI), Generative UI ve Çift Dil (TR / EN) Kuralları

1. **Görsel Kart Zenginliği (Generative UI):**
   * AI Koç bir kompozisyondan bahsettiğinde yalnızca metin yazmamalı; `card_builder.py` üzerinden o kompozisyonun **şampiyon ikonlarını, yıldızlarını, BiS eşyalarını, 4x7 tahta dizilimini ve tek tıkla Team Planner Kodu Kopyalama butonunu** içeren `partials/comp_card.html` bileşenini mesajın altına eklemelidir.
2. **Yüksek Kontrastlı Hextech Koyu Tema:**
   * Zemin rengi `#0a0e17`, yüzeyler `#121722` / `#0d121c`, kenarlıklar `#222d42` ve vurgu rengi `#f0c374` (Hextech Altını) olarak korunmalıdır. Soluk gri metinler (`text-zinc-500`) kullanılmamalıdır.
3. **Çift Dilli (TR / EN) Tam Destek:**
   * Hem arayüz hem de AI Koç yanıtları kullanıcının seçtiği dile (`tr` veya `en`) göre çalışmalıdır.

---

## 4. Güvenlik, Ortam Değişkenleri ve Git Kuralları

1. **`main` Dalı Koruması:**
   * Riot Production API Key incelemesi süresince `main` dalındaki statik GitHub Pages yapısı bozulmamalı; tüm Django geliştirmeleri `v2-chat-platform` dalında yapılmalıdır.
2. **Gizli Anahtarlar ve `.env`:**
   * `DJANGO_SECRET_KEY`, `GEMINI_API_KEY`, `RIOT_API_KEY` ve `DATABASE_URL` kesinlikle kod içine gömülmemeli, ortam değişkenlerinden okunmalıdır.
3. **Satır Sonu (LF) ve Test Zorunluluğu:**
   * Tüm dosyalar UTF-8 ve `\n` (LF) satır sonuyla kaydedilmeli; her görev (task) sonunda hem mevcut `pytest` testleri hem de Django testleri (`python manage.py test`) çalıştırılarak doğrulanmalıdır.
