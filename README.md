# Temp Mail MVP

Bu proje `axione.xyz` icin kendi temp mail servisini kurmanin ilk omurgasini saglar:

- Web arayuzu ile inbox olusturma, izleme ve temizleme
- Dahili SMTP alicisi ile mailleri veritabanina kaydetme
- API ile inbox ve mesaj verilerini cekme veya silme
- OTP / dogrulama kodlarini metin ve HTML govdeden ayiklama
- TTL ve inbox basina mesaj limiti ile temel temizlik

## Hemen calistir

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 run.py
```

Web arayuzu: `http://127.0.0.1:8080`

SMTP portu: `25`

Not: Linux'ta `25` portu icin uygulamayi root ile calistirman veya `setcap` kullanman gerekir.

## Tek komutla baslatma

- Linux / Ubuntu: `bash start.sh`
- Windows CMD: `start.bat`
- Windows PowerShell: `powershell -ExecutionPolicy Bypass -File .\start.ps1`

Bu scriptler sunlari otomatik yapar:

- `.venv` olusturur
- bagimliliklari kurar
- `.env` yoksa olusturur
- web portunu otomatik secer (`8080`, doluysa baska bos port)
- SMTP portunu otomatik secer (`25`, uygun degilse `2525` ve devamindaki bos portlar)
- uygulamayi baslatir

Not:

- Gercek dis mail almak icin SMTP'nin sonunda `25` portunda calismasi gerekir.
- Otomatik secim test ve ilk kurulum icin kolaylik saglar; MX kaydi aktif kullanimda uygulama portuyla ayni olmali.

## Ornek SMTP testi

```bash
python3 - <<'PY'
import smtplib
from email.message import EmailMessage

msg = EmailMessage()
msg["Subject"] = "Your login code is 482913"
msg["From"] = "robot@example.org"
msg["To"] = "tmp-demo@axione.xyz"
msg.set_content("Use 482913 to finish signing in.")

with smtplib.SMTP("127.0.0.1", 25) as smtp:
    smtp.send_message(msg)
PY
```

## API rotalari

- `POST /api/inboxes`
- `GET /api/inboxes/{address}/messages`
- `GET /api/messages/{id}`
- `DELETE /api/inboxes/{address}/messages`
- `DELETE /api/messages/{id}`
- `GET /api/config`
- `GET /healthz`

## Ek dokumantasyon

- API key / servis ihtiyaclari: `docs/API_KEYS_AND_SERVICES.md`

## axione.xyz icin hedef kurulum

- Mail adresleri: `anything@axione.xyz`
- Web arayuzu ve API: `https://mail.axione.xyz`
- SMTP MX host: `mx1.axione.xyz`

## DNS plani

Cloudflare DNS tarafinda:

- `mail` -> `CNAME` -> Cloudflare Tunnel hostname, `Proxied`
- `mx1` -> `A` -> RDP sunucunun public IP'si, `DNS only`
- `@` -> `MX` -> `mx1.axione.xyz` priority `10`
- `@` -> `TXT` -> `v=spf1 mx -all`
- `_dmarc` -> `TXT` -> `v=DMARC1; p=none; adkim=s; aspf=s`

Not:

- Cloudflare Tunnel web/API icin kullanilir.
- SMTP/MX icin `mx1.axione.xyz` kaydi `DNS only` olmak zorunda.
- Mail alma icin firewall'da `25/tcp` acik olmali.

## RDP sunucuda acilacak portlar

- `25/tcp` -> SMTP alma
- `8080/tcp` -> uygulama localde; sadece tunnel veya reverse proxy erisebilir

## Systemd servis dosyasi

Hazir ornek: `deploy/tempmail.service`

Kopyalama:

```bash
sudo cp deploy/tempmail.service /etc/systemd/system/tempmail.service
sudo systemctl daemon-reload
sudo systemctl enable --now tempmail
sudo systemctl status tempmail
```

## Cloudflared tunnel konfigurasyonu

Hazir ornek: `deploy/cloudflared-config.yml`

Bu dosyada tunnel ID ve credentials path alanlarini kendi degerlerinle degistir.

## Uretime gecmeden once bilmen gerekenler

- Cloudflare Tunnel sadece web arayuzu ve HTTP API icin uygundur.
- SMTP / MX trafigi Cloudflare Tunnel uzerinden calismaz; bu trafik icin dogrudan sunucu IP'si, uygun firewall kurallari ve MX kaydi gerekir.
- `her yerde gecer` garanti edilemez. Bir cok servis temp mail patternlerini ve dogrudan domain blacklistlerini kontrol eder.
- Yine de teknik tarafi saglam kurmak icin stabil MX, temiz DNS, rate limit, retention ve loglama gerekir.
