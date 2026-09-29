# Pampers monitor 🍼

Svaka 3 sata provjerava cijene Pampers pelena na webshopovima i šalje poruku
na **Telegram** kad:

- cijena **padne** u odnosu na prošlu provjeru, ili
- cijena bude **jednaka ili ispod tvoje granice** (`target_price`).

Radi besplatno na GitHub Actions i ne treba ti server.

## 1. Napravi Telegram bota (5 min)

1. U Telegramu otvori **@BotFather** → `/newbot` → daj mu ime.
   Dobit ćeš **token** (npr. `123456:ABC-...`).
2. Otvori svog novog bota i pošalji mu bilo koju poruku (npr. `bok`).
3. U browseru otvori `https://api.telegram.org/bot<TOKEN>/getUpdates`
   i pronađi `"chat":{"id": 123456789 ...}`. Taj broj je tvoj **chat id**.

## 2. Dodaj tajne u GitHub

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Ime                  | Vrijednost      |
|----------------------|-----------------|
| `TELEGRAM_BOT_TOKEN` | token od BotFathera |
| `TELEGRAM_CHAT_ID`   | tvoj chat id    |

Zatim **Actions → Pampers monitor → Run workflow** uz kvačicu
*"Samo pošalji probnu poruku"*. Trebala bi ti stići poruka ✅.

## 3. Upiši proizvode u `config.json`

```json
{
  "products": [
    {
      "name": "Pampers Premium Care 4",
      "shop": "Shop A",
      "url": "https://shop-a.hr/pampers-premium-care-4",
      "target_price": 15.00
    }
  ]
}
```

- `url` je link na **stranicu proizvoda**, ne na pretragu.
- `target_price` nije obavezan. Bez njega dobivaš poruke samo kad cijena padne.
- Isti proizvod u više shopova upiši kao više stavki.

Skripta sama traži cijenu na stranici (schema.org JSON-LD, `product:price:amount`
meta tag ili `itemprop="price"`), što pokriva većinu webshopova. Ako za neki
shop javi *"cijena nije pronađena"*, dodaj proizvodu vlastiti regex:

```json
"price_regex": "class=\"product-price\"[^>]*>([\\d.,]+)"
```

(Sličan je `REGEXP_SUBSTR` u Oracleu: prva grupa u zagradama je cijena.)

## Kako radi

- `monitor.py` je jedna Python skripta bez vanjskih biblioteka.
- `state.json` pamti zadnju viđenu cijenu. Action ga nakon svakog pokretanja
  commita natrag u repo, pa istu akciju ne dobivaš dvaput.
- Raspored mijenjaš u `.github/workflows/monitor.yml` (`cron`, vrijeme je UTC).

Lokalno pokretanje:

```bash
export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...
python monitor.py                 # provjeri cijene
python monitor.py --test-telegram # samo probna poruka
python -m unittest tests/test_monitor.py
```
