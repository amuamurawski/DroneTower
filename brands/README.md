# Ikona integracji

Home Assistant nie bierze ikony integracji z tego repozytorium. Pobiera ją z
`https://brands.home-assistant.io/<domena>/icon.png`, a ta domena jest serwowana
z repozytorium [home-assistant/brands](https://github.com/home-assistant/brands).
Dopóki nie ma tam wpisu dla `dronetower_amu`, w panelu integracji widnieje
**„icon not available"** — i nie da się tego obejść lokalnie.

Pliki w `custom_integrations/dronetower_amu/` są przygotowane pod zgłoszenie tam PR-a.

## Jak zgłosić

```bash
git clone https://github.com/<twój-fork>/brands.git
cd brands
mkdir -p custom_integrations/dronetower_amu
cp <to-repo>/brands/custom_integrations/dronetower_amu/*.png \
   custom_integrations/dronetower_amu/
git checkout -b add-dronetower-amu
git commit -am "Add DroneTower-AMU"
git push
```

Potem PR do `home-assistant/brands`. Wymagania, które te pliki już spełniają:

| Plik | Rozmiar | Stan |
| --- | --- | --- |
| `icon.png` | dokładnie 256×256 | ✅ |
| `icon@2x.png` | dokładnie 512×512 | ✅ |
| format | PNG z kanałem alfa, przezroczyste tło | ✅ |
| kadrowanie | bez zbędnego marginesu wokół znaku | ✅ |

Katalog musi nazywać się dokładnie tak jak `domain` w `manifest.json`, czyli
`dronetower_amu` — inaczej Home Assistant nie skojarzy ikony z integracją.

Po scaleniu PR-a ikona pojawi się automatycznie, bez aktualizacji integracji.

## Regeneracja

```bash
.venv/bin/python tools/make_icon.py
```

Znak to kwadrokopter widziany z góry wewnątrz dwóch pierścieni oznaczających
monitorowany promień. Rysowany w 2048 px i zmniejszany, bo Pillow nie ma
własnego antyaliasingu.
