# TFT Set 18 Meta & Patch Telemetry — Geliştirme ve Yol Haritası Planı (PLAN.md)

Bu belge, projede şu ana kadar tamamlanan aşamaları ve mevcut mimari üzerine inşa edilecek sonraki adımları takip etmek için oluşturulmuştur.

---

## Tamamlanan Aşamalar (Mevcut Durum)

- [x] **Faz 1: Çekirdek Veri Hattı ve Matematiksel Diff Motoru**
  - CommunityDragon & DataDragon otomatik sürüm çözücü (`src/cdragon_client.py`).
  - Şampiyon temel istatistikleri ve 1/2/3 yıldız yetenek ölçeklemeleri için ağırlıklı yama farkı hesaplayıcı (`src/diff_engine.py`).
  - MetaTFT Master+ kompozisyon kümeleme, BiS eşya dizilimleri, resmi Team Planner kodu üretimi ve Riot API entegrasyonu (`src/riot_client.py`).
- [x] **Faz 2: Çift Dilli (TR/EN) Statik Dashboard ve CI/CD Otomasyonu**
  - Yüksek kontrastlı Hextech koyu temalı Jinja2 şablonu (`templates/index.html.j2`).
  - İnteraktif "Elimdeki Eşyayla Ne Oynanır?" (Item-to-Comp Matcher) aracı ve 7 bölgeli Challenger liderlik tablosu.
  - 4 aşamalı GitHub Actions iş akışı (`.github/workflows/tft-meta-pipeline.yml`).
- [x] **Faz 3: Yapay Zekâ Bilgi Bankası (RAG) ve Sunucusuz AI Koç**
  - `docs/llms.txt`, `docs/llms-full.txt` ve `docs/api/rag_context.json` üreticisi (`src/rag_builder.py`).
  - Cloudflare Worker tabanlı Gemini (`gemini-3.5-flash`) RAG vekili (`worker/src/index.js`) ve canlı sohbet penceresi.
- [x] **Faz 4: Set 18 Eklenti Tier Listesi ve Özel Mekanik Telemetrisi**
  - 261 Set 18 eklentisi için Master+ Tier (S/A/B/C), aşama (`2-1`, `3-2`, `4-2`), kazanma/ilk 4 oranları ve sinerji kompozisyonları (`panel-augments`).
  - 20 Set 18 Karşılaşması (Encounters/Portals) ve 23 Dükkân Tılsımı (Shop Charms) için strateji ve zamanlama rehberi (`panel-mechanics`).
  - Eklenti ve mekaniklerin RAG bilgi bankasına (440 chunk) ve birim testlerine (`tests/test_mechanics.py`) dahil edilmesi.
- [x] **Faz 5: Mimari ve Standart Dokümantasyonu**
  - `ARCHITECTURE.md`, `RULES.md` ve `PLAN.md` dosyalarının mevcut kod yapısına birebir uygun olarak kök dizinde oluşturulması.

---

## Sıradaki Adımlar (Hedeflenen Geliştirmeler)

### Aşama 1: CI/CD ve Dokümantasyon Senkronizasyonu
- [ ] **GitHub Actions `paths-ignore` Güncellemesi:** `.github/workflows/tft-meta-pipeline.yml` içindeki `paths-ignore` listesine `ARCHITECTURE.md`, `RULES.md` ve `PLAN.md` dosyalarının eklenmesi (salt dokümantasyon güncellemelerinin gereksiz pipeline çalışmasını tetiklememesi için).
- [ ] **README.md Güncellemesi:** `README.md` içindeki klasör ağacına yeni eklenen `tests/test_mechanics.py`, `ARCHITECTURE.md`, `RULES.md`, `PLAN.md` dosyalarının ve yeni Eklenti / Set 18 Mekanik özelliklerinin yansıtılması.

### Aşama 2: İleri Seviye Oyun İçi Telemetri ve Görselleştirme
- [ ] **Özellik (Trait) Kırılım ve Tier Matrisi:** `set18_data["traits"]` ve `live_diff["trait_diffs"]` verilerini kullanarak altın/prizmatik eşik sayılarını (breakpoints) ve yama değişimlerini gösteren interaktif bir "Köken & Özellikler" alt sekmesi eklenmesi.
- [ ] **Kompozisyon Tahta Dizilimi (Hex Positioning Grid):** MetaTFT küme detaylarından (`cluster_details`) gelen hücre koordinatları varsa, kompozisyon çekmecesinde (drawer) 4x7 altıgen TFT tahta diziliminin görselleştirilmesi.
- [ ] **Eklenti -> Kompozisyon Çapraz Filtreleme:** Eklenti Tier Listesi tablosundaki bir sinerji kompozisyonuna tıklandığında doğrudan `Canlı Yama & Meta` sekmesindeki ilgili kompozisyon kartına odaklanma (deep-link) özelliği.

### Aşama 3: AI Koç (Cloudflare Worker) İyileştirmeleri
- [ ] **Dinamik Öneri Soruları:** `templates/index.html.j2` içindeki `AI_CHAT_TEXT.suggestions` listesine Eklenti ve Set 18 Karşılaşma/Tılsım sorularının (ör. *"Altın Şöleni gelince ne oynamalıyım?"*, *"En iyi S-Tier ekonomi eklentileri hangileri?"*) eklenmesi.
- [ ] **Arama Skorlama İyileştirmesi (`worker/src/index.js`):** Kullanıcının sorduğu soruda aşama numarası (`2-1`, `3-2`, `4-2`) veya tılsım maliyeti (`1G`, `2G`) geçtiğinde `retrieve()` fonksiyonunun `augment` ve `charm` tipindeki parçacıklara ek ağırlık vermesi.
