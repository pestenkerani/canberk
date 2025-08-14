# Hotel Logo Fetcher

Bu araç, bir otel/pansiyon listesinden mümkünse resmi logoyu indirir; bulunamazsa siyah zemin üzerinde beyaz yazılı kare bir placeholder üretir.

## Özellikler
- Website domain biliniyorsa Clearbit üzerinden logo denemesi
- Domain yoksa (opsiyonel) Bing Search API ile resmi siteyi bulma denemesi
- Bulunamazsa kare placeholder üretimi
- Çıktı kare olacak şekilde üretilir
- Pillow kuruluysa PNG; kurulu değilse bağımlılıksız SVG çıktısı üretir

## Kurulum
Ek bir kurulum gerekmiyor. Sisteminizde `python3` olması yeterli.

Opsiyonel: PNG çıktı istiyorsanız Pillow kurabilirsiniz (mümkün değilse SVG ile devam edebilirsiniz):
```bash
python3 -m pip install --user Pillow
```

## Kullanım
- CSV ile (önerilir): CSV başlıkları: `name, website, instagram, city` (sadece `name` zorunlu)
```bash
python3 logo_fetcher.py --input hotels.csv --outdir logos --size 1024
```

- Tek kayıt:
```bash
python3 logo_fetcher.py --name "Otel Adı" --website "https://ornek.com" --outdir logos --size 1024
```

### Opsiyonel: Resmi site keşfi için Bing Search API
Resmi domain bilinmiyorsa, Bing Search API anahtarınızı ayarlayabilirsiniz:
```bash
export BING_API_KEY="<YOUR_KEY>"
# veya
export BING_SEARCH_V7_SUBSCRIPTION_KEY="<YOUR_KEY>"
```
Ardından:
```bash
python3 logo_fetcher.py --input hotels.csv --outdir logos
```

## Çıktılar
- Pillow varsa: `logos/*.png`
- Pillow yoksa: `logos/*.svg` (kare tuval; Clearbit logosu SVG içine gömülür, placeholder siyah arka planlı beyaz yazı olarak oluşturulur)

## Notlar ve Sınırlar
- Instagram profil fotoğrafını otomatik almak güvenilir şekilde yetkili API/oturum gerektirir; bu prototipte yok. İstenirse sonraki aşamada eklenebilir.
- Clearbit, domain bazlı çalışır; zincir/marka siteleri için marka logosu dönebilir.
- PNG üretimi için Pillow opsiyoneldir; yoksa araç SVG üretir.

## Örnek CSV
```csv
name,website,instagram,city
Hilton Istanbul Bosphorus,https://www.hilton.com,,Istanbul
Butik Pansiyon,,,Izmir
```