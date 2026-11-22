<div align="center">
  <img src=".github/assets/banner.svg" alt="TFT Meta &amp; Patch Telemetry Banner" width="100%" />

  <p>
    <a href="https://apexq.github.io/TFT-Meta-Patch-Telemetry/">
      <img src="https://img.shields.io/badge/Canl%C4%B1%20Pano-GitHub%20Pages-c89b3c?style=flat-square&amp;logo=githubpages&amp;logoColor=white" alt="Live Dashboard" />
    </a>
    <a href="https://github.com/Apexq/TFT-Meta-Patch-Telemetry/actions/workflows/tft-meta-pipeline.yml">
      <img src="https://github.com/Apexq/TFT-Meta-Patch-Telemetry/actions/workflows/tft-meta-pipeline.yml/badge.svg" alt="TFT Meta Pipeline" />
    </a>
    <img src="https://img.shields.io/badge/TFT-Set%2018%20%2B%20Set%2019%20PBE-0ea5e9?style=flat-square" alt="TFT Set 18 + Set 19 PBE" />
    <img src="https://img.shields.io/badge/Riot%20Games-Policy%20Compliant-10b981?style=flat-square&amp;logo=riotgames&amp;logoColor=white" alt="Riot Games Policy Compliant" />
    <a href="LICENSE">
      <img src="https://img.shields.io/badge/License-Proprietary-1e293b?style=flat-square" alt="Proprietary License" />
    </a>
  </p>

  <p>
    <strong>Kişisel Teamfight Tactics Canlı Yama Telemetri &amp; Set 19 PBE Erken Bakış Platformu</strong><br />
    <em>Otomatik Master+ Meta Analizi &bull; Yama Denge Farkları (Buff/Nerf) &bull; Set 19 PBE Kataloğu &bull; Çift Dil (TR / EN)</em>
  </p>
</div>

---

## Proje Hakkında

**TFT Meta & Patch Telemetry**, Teamfight Tactics için geliştirdiğim kişisel ve tamamen otomatik çalışan bir **meta istihbarat ve yama takip platformudur**. Her yeni canlı yama ve PBE güncellemesi otomatik olarak algılanır; şampiyon/özellik denge değişiklikleri, Master+ kompozisyon trendleri ve yeni set önizlemeleri çift dilli (`TR / EN`) canlı web panosunda yayınlanır.

* **Canlı Web Panosu:** [apexq.github.io/TFT-Meta-Patch-Telemetry](https://apexq.github.io/TFT-Meta-Patch-Telemetry/)

---

## Öne Çıkan Özellikler

| Özellik | Açıklama |
| :--- | :--- |
| **Otomatik Yama &amp; Buff/Nerf Motoru** | CommunityDragon verileri üzerinden 1/2/3 yıldızlı yetenek ve temel istatistik farklarını matematiksel etki puanıyla (`impact_score`) hesaplar |
| **Master+ Kompozisyon &amp; BiS Analizi** | Yüksek eloda öne çıkan kompozisyonlar, seviye temposu (`Fast 8`, `Slow Roll`), ana taşıyıcı BiS eşyaları ve tek tık Team Planner kodları |
| **Dinamik Set 19 PBE Erken Bakış** | PBE üzerinde yeni set geçişini otomatik tespit eder; 5G–1G maliyet filtreli şampiyon kataloğu, yeni özellikler ve erken dikey sinerji önizlemeleri sunar |
| **Bölgesel Challenger Sıralaması** | Resmi Riot Games API üzerinden bölgesel Challenger / Grandmaster LP barajları ve üst sıralama takibi |
| **Çift Dil Deneyimi (`TR / EN`)** | Tüm analiz özetleri, şampiyon/özellik isimleri ve arayüz bileşenlerinde anlık Türkçe / İngilizce geçişi |

---

## Sistem Akışı

```mermaid
flowchart LR
    Sources["CommunityDragon &amp; MetaTFT &amp; Riot API"] --> Detector["Otomatik Yama &amp; PBE Algılayıcı"]
    Detector --> Diff["Denge Farkı &amp; Master+ Analiz Motoru"]
    Diff --> Synthesis["Çift Dilli Özet &amp; Bilgi Tabanı"]
    Synthesis --> Pages["Canlı Web Panosu (GitHub Pages)"]
```

---

## Erişim, Atıf ve Lisans

Bu repo **canlı web servisini barındırmak, kişisel proje vitrini sunmak ve Riot Games Geliştirici Politikası şeffaflığını sağlamak** amacıyla herkese açık tutulmaktadır.

* **Üçüncü Taraf Kurulum Desteklenmez:** Kişisel bilgisayarlara veya harici sunuculara kurulum/çoğaltma için açık kaynak proje olarak sunulmaz.
* **Lisans &amp; Güvenlik:** Tüm hakları saklıdır ([LICENSE](LICENSE)) &bull; Güvenlik bildirimleri için [SECURITY.md](SECURITY.md).
* **Veri Atıfları:** Master+ kompozisyon kümeleri [MetaTFT.com](https://www.metatft.com), oyun verileri [CommunityDragon](https://communitydragon.org/) &amp; Riot DataDragon, bölgesel sıralamalar [Riot Games Developer API](https://developer.riotgames.com/) kaynaklarından sağlanmaktadır.

---

## Riot Games Yasal Uyarı &amp; Politika Uyumu

**TFT Meta & Patch Telemetry**, Riot Games tarafından desteklenmemektedir ve Riot Games'in veya Riot Games ürünlerinin oluşturulmasında ya da yönetilmesinde resmi olarak yer alan kişilerin görüş ve düşüncelerini yansıtmaz. Riot Games ve Teamfight Tactics, Riot Games, Inc.'nin ticari markaları veya tescilli ticari markalarıdır.

* **Augment Politikası Uyumu:** Riot Games Geliştirici Politikaları gereği eklentilere (Augment) ait sayısal kazanma oranı, ortalama sıralama veya seçilme yüzdeleri rapor ve panolarda yayınlanmaz; eklentiler yalnızca nitel kademe ve aşama rehberliğiyle sunulur.
