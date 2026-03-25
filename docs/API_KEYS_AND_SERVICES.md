# API Keys and Service Requirements

Bu dokuman, `axione-tempmail` kurulumunda hangi servislerin gerekli oldugunu, hangi alanlarda API key veya token gerektigini ve hangilerinin zorunlu olmadigini netlestirir.

## Kisa Ozet

- Uygulamanin cekirdek mail alma yapisi icin harici API key gerekmez.
- Mail alma icin gereken temel seyler: bir sunucu, `25/tcp` acik port, dogru DNS/MX kayitlari ve calisan SMTP servisi.
- Web arayuzu icin Cloudflare Tunnel kullanacaksan Cloudflare hesabi gerekir.
- Cloudflare Tunnel tarafinda klasik bir "API key" zorunlu degil; fakat tunnel olusturma ve yonetme icin Cloudflare kimlik dogrulamasi gerekir.
- GitHub deploy, CI/CD veya monitoring eklenecekse bunlar ayri servis/token gerektirebilir, ama mevcut repo bunlara bagimli degil.

## Bu Proje Hangi Dis Servislere Bagli?

Mevcut kod tabani asagidaki temel parcalarla calisir:

- Web uygulamasi: FastAPI
- UI: server-side template + Alpine.js
- Veritabani: SQLite
- Mail alma: dahili SMTP listener
- DNS: domain yonetimi icin dis DNS saglayici
- Opsiyonel HTTP yayinlama: Cloudflare Tunnel veya reverse proxy

Mevcut haliyle proje; SendGrid, Resend, Mailgun, AWS SES inbound, Postmark inbound veya benzeri ucretli inbound API servislerine mecbur degildir.

## API Key Gereken ve Gerekmeyen Alanlar

### 1) Mail alma (SMTP inbound)

API key gerekir mi?

- Hayir.

Ne gerekir?

- Domain kontrolu (`axione.xyz`)
- DNS yonetimi
- `MX` kaydi
- `A` kaydi veya uygun host yonlendirmesi
- Sunucuda `25/tcp` acik port
- Uygulamanin SMTP listener olarak ayakta olmasi

Not:

- En kritik kisim API key degil, dogru MX ve port 25 erisimidir.
- Bir cok VPS/RDP saglayicisi outbound 25'i veya bazen inbound mail trafigini kisitlayabilir. Sunucu saglayicinda bunu ayrica kontrol etmek gerekir.

### 2) Web arayuzu yayinlama

API key gerekir mi?

- Dogrudan uygulama icin hayir.
- Cloudflare Tunnel kullanirsan Cloudflare hesabina giris gerekir.

Ne gerekir?

- `mail.axione.xyz` host'u
- HTTP servisine erisim
- Opsiyonel Cloudflare Tunnel veya Nginx/Caddy reverse proxy

Cloudflare tarafinda ne tip bilgi gerekir?

- Cloudflare hesap erisimi
- Tunnel ID
- Tunnel credentials JSON dosyasi

Bu repo icinde nerede kullaniliyor?

- `deploy/cloudflared-config.yml`

Ornek:

```yml
tunnel: REPLACE_WITH_TUNNEL_ID
credentials-file: /etc/cloudflared/REPLACE_WITH_TUNNEL_ID.json

ingress:
  - hostname: mail.axione.xyz
    service: http://127.0.0.1:8080
  - service: http_status:404
```

### 3) Admin girisi

API key gerekir mi?

- Hayir.

Ne gerekir?

- `.env` icinde admin kullanici bilgileri

Degiskenler:

```env
TEMPMAIL_ADMIN_USERNAME=admin
TEMPMAIL_ADMIN_PASSWORD=change-me-now
```

Onemli:

- Production ortaminda varsayilan sifre kesinlikle degistirilmeli.
- Bu bilgi API key degil ama hassas gizli bilgidir.

### 4) Veritabani

API key gerekir mi?

- Hayir.

Mevcut varsayilan:

```env
TEMPMAIL_DB_URL=sqlite:///./tempmail.db
```

Not:

- Buyuk trafik durumunda SQLite yerine Postgres gibi bir veritabani dusunulebilir.
- Su anki projede SQLAlchemy kullanildigi icin ileride farkli DB'ye gecis daha kolaydir.

### 5) Ucuncu parti mail gonderim servisleri

API key gerekir mi?

- Su anki sistemin mail alma tarafi icin hayir.

Ne zaman gerekir?

- Sistemden disari mail gondermek istersen
- Transactional email gondermek istersen
- "Invite", "password reset", "notification" gibi outbound email akislari eklersen

O durumda kullanilabilecek servisler:

- Resend
- SendGrid
- Mailgun
- AWS SES
- Postmark

Bu projede su an bunlardan hicbiri zorunlu degil.

## Cloudflare Tarafinda Gerekenler

Cloudflare kullaniyorsan su bilesenler gerekir:

- Domain Cloudflare DNS'te olmali veya DNS yetkisi sende olmali
- `mail.axione.xyz` kaydi
- Opsiyonel tunnel kurulumu
- `mx1.axione.xyz` kaydi `DNS only`

Ornek DNS plani:

- `mail` -> `CNAME` -> Cloudflare Tunnel hostname (`Proxied`)
- `mx1` -> `A` -> sunucu public IP (`DNS only`)
- `@` -> `MX` -> `mx1.axione.xyz` priority `10`
- `@` -> `TXT` -> `v=spf1 mx -all`
- `_dmarc` -> `TXT` -> `v=DMARC1; p=none; adkim=s; aspf=s`

Cloudflare API token gerekli mi?

- Elle dashboard uzerinden kurulum yaparsan zorunlu degil.
- Eger tunnel, DNS veya deploy otomasyonunu script ile yonetmek istersen evet, o zaman API token gerekir.

Bu repo su an Cloudflare API token istemiyor.

## Sunucuda Gereken Servisler

Minimum production benzeri kurulum icin:

- Python 3
- Virtualenv
- Systemd veya benzeri servis yoneticisi
- Acik `25/tcp`
- Web icin `8080` veya belirledigin HTTP portu

Repo icindeki hazir servis dosyasi:

- `deploy/tempmail.service`

Bu servis su mantikla calisir:

- uygulama klasorunde calisir
- `.env` dosyasini yukler
- `run.py` baslatir
- hata alirsa tekrar ayaga kalkar

## .env Icindeki Onemli Alanlar

Mevcut ornek dosya: `.env.example`

Temel alanlar:

```env
TEMPMAIL_DB_URL=sqlite:///./tempmail.db
TEMPMAIL_WEB_HOST=0.0.0.0
TEMPMAIL_WEB_PORT=8080
TEMPMAIL_SMTP_HOST=0.0.0.0
TEMPMAIL_SMTP_PORT=25
TEMPMAIL_ACCEPTED_DOMAINS=axione.xyz
TEMPMAIL_ALLOW_ANY_DOMAIN=false
TEMPMAIL_POLL_SECONDS=8
TEMPMAIL_MESSAGE_TTL_HOURS=24
TEMPMAIL_TEMP_INBOX_MINUTES=5
TEMPMAIL_TEMP_DAILY_LIMIT=3
TEMPMAIL_MAX_MESSAGES_PER_INBOX=100
TEMPMAIL_MAX_INBOXES=10000
TEMPMAIL_SESSION_HOURS=72
TEMPMAIL_SECURE_COOKIES=false
TEMPMAIL_ADMIN_USERNAME=admin
TEMPMAIL_ADMIN_PASSWORD=change-me-now
```

Production icin dikkat:

- `TEMPMAIL_ADMIN_PASSWORD` guclu olmali
- HTTPS varsa `TEMPMAIL_SECURE_COOKIES=true` yapilmali
- `TEMPMAIL_SMTP_PORT=25` gercek inbound mail icin tercih edilmeli
- `TEMPMAIL_ACCEPTED_DOMAINS` dogru domainlerle sinirlanmali

## Hangi Bilgiler Gizli Saklanmali?

Asagidakiler repoya pushlanmamali:

- `.env`
- admin sifresi
- Cloudflare tunnel credentials JSON
- Cloudflare API token varsa o
- herhangi bir SMTP auth sifresi eger sonradan outbound eklenirse
- production database dump'lari

## Hangi Durumda Gercekten API Token Lazim Olur?

Asagidaki senaryolarda ek token veya secret gerekir:

- Cloudflare DNS kayitlarini otomatik ac/kapat yapmak
- Tunnel olusturmayi script ile otomatiklestirmek
- GitHub Actions ile secrets kullanarak deploy etmek
- Dis mail gonderim servisi baglamak
- Harici monitoring/alerting servisi baglamak

Mevcut repo icin bunlar opsiyoneldir.

## En Sade Production Kontrol Listesi

Asagidaki maddeler tamamsa sistem calisir:

1. Domain DNS yonetimi sende
2. `mail.axione.xyz` web icin dogru yere gidiyor
3. `mx1.axione.xyz` sunucu IP'sine gidiyor
4. Domain `MX` kaydi `mx1.axione.xyz` gosteriyor
5. Sunucuda `25/tcp` acik
6. Uygulama systemd ile ayakta
7. `.env` icinde admin sifresi degistirildi
8. Web arayuzu `https://mail.axione.xyz` uzerinden aciliyor

## Bu Proje Icin Net Cevap

"API key istiyor mu?"

- Mail alma cekirdegi icin: hayir
- Cloudflare tunnel otomasyonu icin: opsiyonel olarak evet
- Cloudflare dashboard ile manuel kurulum icin: hayir
- Admin girisi icin: API key degil, `.env` icinde sifre gerekir
- Ucuncu parti outbound mail servisi icin: ozellik eklenirse evet

## Onerilen Sonraki Adim

Bu dokumandan sonra ayrica su belgeler yararli olur:

- production kurulum rehberi
- Cloudflare adim adim tunnel kurulumu
- DNS/MX troubleshooting rehberi
- SMTP test komutlari ve hata senaryolari
