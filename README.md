# Praćenje cijena na webshopovima

Jednostavna skripta koja provjerava cijene proizvoda na više webshopova i šalje
push obavijest na mobitel kad cijena padne **ispod zadanog praga** (trenutno 28 €, mijenja se u `config.yaml`).

## Kako radi

1. U `config.yaml` upišeš URL-ove proizvoda (s bilo kojeg shopa).
2. Skripta otvori svaku stranicu i pročita cijenu – automatski iz schema.org
   JSON-LD / meta podataka (to ima većina shopova), ili preko CSS `selector`-a
   koji sam navedeš.
3. Kad cijena padne ispod praga, šalje obavijest preko [ntfy](https://ntfy.sh).
   Obavijest stiže samo **jednom** po padu – ponovno tek kad cijena poraste pa
   opet padne (stanje se čuva u `state.json`).

## Postavljanje obavijesti

1. Instaliraj aplikaciju **ntfy** (Android / iOS).
2. Izmisli teško pogodivo ime topica, npr. `cijene-kristijan-8f3k2`, i pretplati
   se na njega u aplikaciji.
3. Upiši ga u `config.yaml` (`notify.ntfy_topic`) ili – bolje – kao GitHub
   secret `NTFY_TOPIC` (Settings → Secrets and variables → Actions).

## Automatsko pokretanje (GitHub Actions)

Workflow `.github/workflows/price-check.yml` pokreće provjeru svakih sat vremena
i sprema `state.json` natrag u repo. Može se pokrenuti i ručno iz kartice
**Actions → Provjera cijena → Run workflow**.

## Lokalno pokretanje

```bash
pip install -r requirements.txt
python price_tracker.py              # koristi config.yaml i state.json
python -m pytest                     # testovi (pip install pytest)
```

## Dodavanje proizvoda

```yaml
products:
  - name: "Slušalice"
    url: "https://www.nekishop.hr/proizvod/slusalice"
  - name: "Knjiga"
    url: "https://www.drugishop.hr/knjiga"
    selector: ".product-price"   # ako automatsko čitanje ne uspije
    threshold: 15                # vlastiti prag za ovaj proizvod
```

Ako se za neki proizvod ispiše `cijena nije pronađena`, otvori stranicu u
pregledniku, desni klik na cijenu → *Inspect* i prepiši CSS klasu u `selector`.
