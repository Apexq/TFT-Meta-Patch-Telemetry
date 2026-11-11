# TFT Set 18 Meta & Patch Telemetry — Kodlama Standartları ve Kurallar (RULES.md)

Bu belge, mevcut kod tabanının kararlılığını, veri doğruluğunu ve CI/CD işleyişini korumak için yapılacak tüm geliştirmelerde uyulması zorunlu teknik kuralları tanımlar.

---

## 1. Kapsam ve Oyun Verisi Kuralları

1. **Kesin Set 18 (`TFTSet18`) Odaklanması:**
   * Tüm veri çekme ve filtreleme işlemleri [`src/__init__.py`](file:///C:/Users/besir_secilmis/.gemini/antigravity/scratch/tft-meta-analyzer/src/__init__.py) içindeki `TARGET_MUTATOR = "TFTSet18"` ve `TARGET_SET_NUMBER = 18` sabitlerine bağlı kalmalıdır.
   * Oynanabilir olmayan kukla/NPC birimleri dışlamak için şampiyon filtrelemesinde `traits and 1 <= cost <= 6` koşulu ([`src/cdragon_client.py`](file:///C:/Users/besir_secilmis/.gemini/antigravity/scratch/tft-meta-analyzer/src/cdragon_client.py)) korunmalıdır.
2. **İkon ve Varlık Çözümleme:**
   * Ham `.tex` veya `.dds` oyun içi dosya yolları doğrudan şablona gönderilmemeli; her zaman `CDragonClient.resolve_icon_url()` veya `RiotTFTAnalyzer.resolve_augment_icon()` üzerinden geçerli `.png` URL'lerine dönüştürülmelidir.
   * Kırık görsel oluşmaması için şablondaki `<img>` etiketlerinde yedek (`onerror`) mekanizması korunmalıdır.
3. **Açıklama (Tooltip) Temizliği:**
   * Riot/MetaTFT verilerinden gelen `<TFTCurveTable row="..."/>` ve HTML/XML etiketleri ham halde arayüze veya RAG dosyalarına basılmamalı; `_clean_curve_tooltip()` fonksiyonu ile gerçek sayısal değerlere çözümlenmelidir.

---

## 2. Çift Dilli (TR / EN) Tam Uyum Kuralı

1. **Veri Katmanı:**
   * `full_report` içine eklenen her metin alanı hem Türkçe (varsayılan anahtar: `name`, `title`, `desc`, `status_tr`, `strategy_tr`) hem İngilizce (`name_en`, `title_en`, `desc_en`, `status_en`, `strategy_en`) karşılığıyla üretilmelidir.
2. **Şablon Katmanı ([`templates/index.html.j2`](file:///C:/Users/besir_secilmis/.gemini/antigravity/scratch/tft-meta-analyzer/templates/index.html.j2)):**
   * Kullanıcıya görünen her metin `<span class="lang-tr">...</span>` ve `<span class="lang-en">...</span>` bloklarıyla sarmalanmalıdır.
   * Arama çubuğu `placeholder` metinleri ve dinamik kopyalama bildirimleri `setLanguage(lang)` fonksiyonu içinde her iki dil için tanımlanmalıdır.
3. **RAG ve AI Koç Katmanı:**
   * [`src/rag_builder.py`](file:///C:/Users/besir_secilmis/.gemini/antigravity/scratch/tft-meta-analyzer/src/rag_builder.py) içindeki `_keywords()` çağrılarına hem Türkçe hem İngilizce terimler gönderilmeli; Türkçe karakter normalizasyonu (`_normalize`: `İ->i`, `I->ı->i`, diakritik temizliği) bozulmamalıdır.

---

## 3. Hata Toleransı ve Kesintisiz Çalışma (Graceful Degradation)

1. **Sıfır Gizli Anahtarla Çalışabilme:**
   * Pipeline, `RIOT_API_KEY`, `GITHUB_TOKEN` veya `DISCORD_WEBHOOK_URL` ortam değişkenleri tanımlı olmadığında da **asla çökmemeli** (`exit code 0` ile tamamlanmalı) ve kural tabanlı yedek mekanizmalarını (`_build_bilingual_rule_based_report`, deterministik Team Planner hex yedekleri vb.) devreye sokmalıdır.
2. **Ağ İstekleri ve Zaman Aşımı:**
   * Tüm dış HTTP isteklerinde (`urllib.request.urlopen`) açık bir `timeout` değeri belirtilmeli ve dış API kesintileri `try / except` bloklarıyla yakalanarak uyarı logu basılıp güvenli varsayılan değerlerle devam edilmelidir.
3. **Jinja2 Şablon Güvenliği:**
   * Şablon içinde opsiyonel veya eksik olabilecek sözlük alanlarına erişirken `UndefinedError` hatasını önlemek için `{% if ... is defined %}` veya `or` varsayılan değerleri kullanılmalıdır.

---

## 4. Arayüz (UI) ve Tasarım Standartları

1. **Yüksek Kontrastlı Koyu Tema:**
   * Arka plan `#0a0e17`, kart yüzeyleri `#121722` / `#0d121c`, kenarlıklar `#222d42` / `#29364f` ve vurgu rengi Hextech altını (`#f0c374`) olarak korunmalıdır.
   * Okunabilirliği düşüren soluk gri sınıflar (`text-zinc-500`, `text-zinc-600`) **kullanılmamalı**; ikincil metinlerde en az `text-slate-400` veya `text-slate-300`, ana metinlerde `text-white` / `text-slate-100` tercih edilmelidir.
2. **Sıfır Derleme (Zero-Build) Statik Çıktı:**
   * Dashboard, harici bir Node.js/Webpack derleme adımına ihtiyaç duymadan doğrudan Jinja2 ile tekil `docs/index.html` dosyası olarak üretilmeye devam etmelidir.

---

## 5. Güvenlik, GitOps ve Platform Kuralları

1. **Gizli Anahtar Hijyeni:**
   * `.env` dosyası, API anahtarları (`RIOT_API_KEY`, `GEMINI_API_KEY`) veya `.cache/` içeriği hiçbir koşulda Git geçmişine eklenmemelidir.
   * Cloudflare Worker gizli anahtarları [`worker/wrangler.toml`](file:///C:/Users/besir_secilmis/.gemini/antigravity/scratch/tft-meta-analyzer/worker/wrangler.toml) içine düz metin olarak yazılmamalı, yalnızca `npx.cmd wrangler secret put GEMINI_API_KEY` ile tanımlanmalıdır.
2. **Satır Sonu (Line Ending) Standardı:**
   * Windows ortamında dosya düzenlerken çift satır boşluğu (CRLF bozulması) oluşmaması için dosyalar UTF-8 ve `\n` (LF) satır sonlarıyla kaydedilmelidir.
3. **Sonsuz Döngü Koruması (CI/CD):**
   * [`.github/workflows/tft-meta-pipeline.yml`](file:///C:/Users/besir_secilmis/.gemini/antigravity/scratch/tft-meta-analyzer/.github/workflows/tft-meta-pipeline.yml) içindeki otomatik bot commit mesajlarında `[skip ci]` ibaresi ve `on.push.paths-ignore` listesi (`docs/**`, `data/state.json`) kesinlikle korunmalıdır.

---

## 6. Test ve Doğrulama Zorunluluğu

Kod tabanında yapılan her değişiklikten sonra commit atılmadan önce aşağıdaki doğrulama adımları eksiksiz çalıştırılmalıdır:

```powershell
# 1. Tüm birim testlerinin geçtiğini doğrula
python -m pytest tests/ -v

# 2. Tam veri hattını çalıştırarak docs/ çıktılarını ve RAG dosyalarını yeniden üret
python -m src.main --force
```
