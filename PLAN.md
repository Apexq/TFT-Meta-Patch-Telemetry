# TFT Set 18 AI Coach Platform — Görev Bazlı Uygulama Planı (PLAN.md)

Bu belge, **`v2-chat-platform`** dalında geliştirilecek **Django Chat-First TFT Yapay Zekâ Koçluk Platformu** için adım adım görev listesini (Task List) içerir. Her görev birbirinden bağımsız olarak test edilebilir şekilde bölünmüştür; sırasıyla **"Task 1'i yap"**, **"Task 2'yi yap"** şeklinde talimat vererek ilerleyebilirsin.

---

## Tamamlanan Hazırlık Aşamaları

- [x] **Faz 0.1: Riot Production API Key Uyumluluğu (`main` dalı)**
  - Eklenti (Augment) sayısal kazanma ve ortalama sıra oranlarının gizlenmesi (`c2cfc86`).
  - `docs/riot.txt` doğrulama dosyasının kalıcı hale getirilmesi (`55016fcd-fe08-40f7-bf33-18a2dbc82a60`).
- [x] **Faz 0.2: Mimari, Veritabanı ve Kural Tasarımı (`v2-chat-platform` dalı)**
  - [`ARCHITECTURE.md`](file:///C:/Users/besir_secilmis/.gemini/antigravity/scratch/tft-meta-analyzer/ARCHITECTURE.md), [`DATABASE.md`](file:///C:/Users/besir_secilmis/.gemini/antigravity/scratch/tft-meta-analyzer/DATABASE.md), [`RULES.md`](file:///C:/Users/besir_secilmis/.gemini/antigravity/scratch/tft-meta-analyzer/RULES.md) ve [`PLAN.md`](file:///C:/Users/besir_secilmis/.gemini/antigravity/scratch/tft-meta-analyzer/PLAN.md) belgelerinin hazırlanması.

---

## Uygulama Görevleri (Sırasıyla Verilecek Tasklar)

### 🔹 TASK 1: Django 5.x Proje İskeleti, Ayarlar ve Veritabanı Modelleri (ORM)
* **Hedef:** Django projesini (`config/` ve `apps/`) kurmak ve [`DATABASE.md`](file:///C:/Users/besir_secilmis/.gemini/antigravity/scratch/tft-meta-analyzer/DATABASE.md) içindeki tüm tabloları oluşturup ilk migration'ları çalıştırmak.
* **Yapılacaklar:**
  1. `requirements.txt` dosyasına `Django>=5.1`, `uvicorn`, `whitenoise` paketlerinin eklenmesi ve kurulması.
  2. `manage.py`, `config/settings.py`, `config/urls.py`, `config/asgi.py` dosyalarının oluşturulması (`/riot.txt` uç noktası dahil).
  3. `apps/core`, `apps/accounts`, `apps/telemetry`, `apps/riot_sync` ve `apps/chat` uygulamalarının oluşturulması.
  4. `UserProfile`, `PatchSnapshot`, `RAGChunk`, `PlayerMatchCache`, `ChatSession`, `ChatMessage` ve `RateLimitLog` modellerinin (`models.py`) ve Django Admin (`/admin`) panellerinin kodlanması.
  5. `python manage.py makemigrations` ve `python manage.py migrate` komutlarıyla veritabanının ayağa kaldırılması ve model birim testlerinin yazılması.

---

### 🔹 TASK 2: Telemetri & RAG Veritabanı Senkronizasyon Motoru (`apps.telemetry`)
* **Hedef:** Mevcut [`src/`](file:///C:/Users/besir_secilmis/.gemini/antigravity/scratch/tft-meta-analyzer/src) veri motorunu Django veritabanına bağlamak ve görsel kart (Generative UI Card) yüklerini indekslemek.
* **Yapılacaklar:**
  1. `python manage.py sync_tft_meta` yönetim komutunun yazılması: Mevcut `data/meta_report.json` ve `docs/api/rag_context.json` verisini (veya `--fetch` ile canlı CDragon/MetaTFT verisini) okuyup `PatchSnapshot` ve 440+ `RAGChunk` kaydı olarak veritabanına yazması.
  2. Her `RAGChunk` kaydına sohbet içinde görsel kart çizdirmek için gereken `ui_card_payload` (şampiyon ikonları, BiS eşyalar, 4x7 tahta dizilimi, Team Planner kodu, Eklenti S/A/B/C rozetleri) JSON verisinin bağlanması.
  3. `apps/telemetry/services.py` içinde Türkçe/İngilizce normalize anahtar kelime ve aşama (`2-1`, `3-2`, `4-2`) destekli hızlı RAG arama (`retrieve_chunks_and_cards`) servisinin yazılması.

---

### 🔹 TASK 3: Chat-First Ana Sayfa Tasarımı ve Yan Çekmeceler (`apps.core` + HTMX UI)
* **Hedef:** Sitenin ana sayfasını (`/`) ChatGPT / Perplexity tarzı tam ekran bir **TFT Set 18 AI Koç** arayüzüne dönüştürmek.
* **Yapılacaklar:**
  1. `templates/django/base.html` ve `templates/django/chat_home.html` şablonlarının Hextech koyu temayla (`#0a0e17` zemin, `#f0c374` altın vurgu) hazırlanması.
  2. **Sol Kenar Çubuğu (Sidebar):** "Yeni Sohbet Başlat" butonu, geçmiş sohbet oturumları (`ChatSession` listesi), hızlı mod seçiciler ve `TR / EN` dil değiştirici.
  3. **Orta Sohbet Ekranı:** Karşılama ekranı, hazır strateji soru kartları, sesli soru sorma (Web Speech API mikrofon butonu) ve mesaj giriş çubuğu.
  4. **Yandan Açılır Canlı Telemetri Çekmeceleri (Slide-Over Drawers):** Sohbetten çıkmadan sağ panelde tek tıkla açılan **Meta Tier List**, **Yama Buff/Nerf**, **Eklenti Rehberi** ve **Set 18 Karşılaşma/Tılsım** çekmeceleri.

---

### 🔹 TASK 4: AI Koç Sohbet Motoru ve Görsel Kompozisyon Kartları (`apps.chat`)
* **Hedef:** Kullanıcı soru sorduğunda hem Gemini LLM koçluk yanıtını hem de altında **interaktif görsel TFT kartlarını** (`comp_card.html`, `augment_card.html`) gerçek zamanlı döndürmek.
* **Yapılacaklar:**
  1. `apps/chat/llm_service.py`: Gemini API (`gemini-2.5-flash` / `gemini-3.5-flash`) entegrasyonu + API anahtarı olmadığında veya hata durumunda yerel RAG verisinden çalışan akıllı kural tabanlı yedek koç motoru.
  2. `apps/chat/card_builder.py`: Yanıtta geçen kompozisyonları, şampiyonları ve eklentileri tespit edip mesajın altına görsel kartları ekleyen servis.
  3. `templates/django/partials/comp_card.html`: Sohbet balonunun içinde **Şampiyon İkonları + BiS Eşyalar + Açılır 4x7 Hex Tahta Dizilimi + Tek Tıkla Team Planner Kodu Kopyalama** kartı.
  4. Mesaj beğenme/beğenmeme (`+1 / -1` feedback) ve IP/Kullanıcı hız sınırlama (`RateLimitLog`) entegrasyonu.

---

### 🔹 TASK 5: "Elimdekilerle Ne Oynarım?" (Opener & Pivot Builder) Aracı
* **Hedef:** Oyuncunun 2-1'de elindeki eşya bileşenlerini ve bulduğu ilk şampiyonları seçerek AI Koç'tan adım adım **Erken Oyun -> 4-2 Pivot Haritası** alması.
* **Yapılacaklar:**
  1. Sohbet kutusunun üstüne açılır/kapanır **"Elimdeki Eşyalar & Başlangıç Seçici"** (`partials/opener_bar.html`) eklenmesi.
  2. Seçilen eşyaları BiS olarak kullanan en yüksek dereceli Master+ kompozisyonların otomatik filtrelenip AI Koç'a özel bir `OPENER_BUILDER` istemiyle gönderilmesi.

---

### 🔹 TASK 6: Riot ID ile "Son Maçımı Analiz Et" (Post-Game AI Review — `apps.riot_sync`)
* **Hedef:** Production API Key ile oyuncunun `RiotID#TAG` (örn. `Oyuncu#TR1`) bilgisini girerek son maçlarını çekmesi ve AI Koç'un maç sonu hata analizi yapması.
* **Yapılacaklar:**
  1. `apps/riot_sync/client.py`: Resmi Riot `account-v1` (PUUID çözümleme), `tft-league-v1` (Lig/LP bilgisi) ve `tft-match-v1` (son maçların detayları) istemcisinin `PlayerMatchCache` önbelleklemesiyle yazılması.
  2. `apps/riot_sync/analyzer.py`: Maçtaki diğer 7 oyuncunun tahtalarını tarayarak **Contested (Lobide kaç kişi aynı şampiyonu aramış)**, **Ekonomi/Seviye temposu** ve **BiS Eşya Uyumluluğu** karnesi çıkaran algoritma.
  3. Sohbet ekranında `"Maç Analizi"` moduna geçildiğinde oyuncunun son maçlarını kart olarak listelemesi ve tek tıkla *"Bu maçta neden 5. oldum, neyi yanlış yaptım?"* analizi üretmesi.

---

### 🔹 TASK 7: Kullanıcı Üyeliği, Misafir Sohbet Aktarımı ve Kota Sistemi (`apps.accounts`)
* **Hedef:** Kullanıcıların kayıt olup giriş yapabilmesi, misafirken yaptıkları sohbetlerin hesaplarına aktarılması ve `RiotID#TAG` profillerini kalıcı bağlamaları.
* **Yapılacaklar:**
  1. Kayıt Ol / Giriş Yap / Çıkış Yap sayfaları ve modal pencereleri.
  2. Giriş yapıldığında tarayıcıdaki `guest_session_key` ile açılmış eski sohbetlerin (`ChatSession`) otomatik olarak kullanıcının hesabına bağlanması (`user_logged_in` sinyali).
  3. Profilde kayıtlı `RiotID#TAG` ve günlük kalan mesaj kotası göstergesi.

---

### 🔹 TASK 8: Production Hazırlığı, Docker/ASGI Yapılandırması ve Domain Bağlantı Rehberi
* **Hedef:** Projeyi alınan gerçek domaine ve bulut sunucuya (Railway / Render / Fly.io / VPS + Cloudflare) tek komutla çıkacak hale getirmek.
* **Yapılacaklar:**
  1. `Dockerfile`, `Procfile` ve `uvicorn` / `gunicorn` üretim ayarlarının hazırlanması.
  2. `CSRF_TRUSTED_ORIGINS`, `ALLOWED_HOSTS`, `WhiteNoise` statik dosya sıkıştırması ve PostgreSQL (`DATABASE_URL`) geçiş ayarlarının tamamlanması.
  3. Cloudflare DNS + SSL + Domain bağlama kılavuzunun (`DEPLOYMENT.md`) oluşturulması ve uçtan uca tüm testlerin (`pytest` + `manage.py test`) doğrulanması.
