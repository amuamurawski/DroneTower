# Historia zmian

Format według [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/),
wersjonowanie według [SemVer](https://semver.org/lang/pl/).

## [1.0.2] — 2026-08-10

### Naprawione

- **Ikona integracji w końcu się wyświetla.** W 1.0.1 leżała w `brands/`, czekając
  na PR do `home-assistant/brands`. To ślepa uliczka: repozytorium `brands`
  **nie przyjmuje już ikon integracji niestandardowych** (PR został automatycznie
  zamknięty), bo od Home Assistant **2026.3** integracja dostarcza je sama.
  Pliki trafiły więc do `custom_components/dronetower_amu/brand/`, skąd Home
  Assistant bierze je bezpośrednio, z pierwszeństwem przed CDN-em. Nie wymaga to
  niczego w `manifest.json`. Szczegóły w
  [ogłoszeniu HA](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api).

### Dodane

- Wariant ikony dla ciemnego motywu (`dark_icon.png`, `dark_icon@2x.png`) —
  granatowy dron z wersji podstawowej ginął na ciemnym tle.

### Usunięte

- Katalog `brands/` i skrypt `tools/gh_brands_pr.py`, niepotrzebne po powyższym.

## [1.0.1] — 2026-08-10

### Zmienione

- Opis urządzenia z angielskiego `DroneTower check-in feed` na
  **Monitor zgłoszonych lotów** — to ten napis widać w wierszu urządzenia.
- `documentation` i `issue_tracker` w manifeście wskazują istniejące repozytorium
  `amuamurawski/DroneTower`. Poprzednie adresy prowadziły donikąd, co blokowało
  walidację HACS.

### Dodane

- Ikona marki wraz z generatorem `tools/make_icon.py`. W tej wersji leżała jeszcze
  w `brands/`, przygotowana pod zgłoszenie do `home-assistant/brands` — patrz 1.0.2.
- `docs/automatyzacje.md`: zapowiedź TTS na głośniku i warianty (powiadomienie na
  telefon, zapowiedź per dron, podbicie głośności, karty na pulpit i mapę).

## 1.0.0 — 2026-08-10

Pierwsza wersja kodu. Istniała wyłącznie jako zawartość gałęzi `main`, nigdy nie
dostała taga ani release'u — pierwszym wydaniem oznaczonym tagiem jest 1.0.1.

### Dodane

- Integracja pokazująca zgłoszone loty dronów wokół wskazanego punktu:
  `binary_sensor` obecności, licznik lotów w zasięgu, odległość do najbliższego,
  diagnostyczny licznik krajowy oraz znaczniki `geo_location` na mapie.
- Zdarzenia `dronetower_amu_drone_detected` i `dronetower_amu_drone_cleared`
  do automatyzacji.
- Konfiguracja przez interfejs: wybór punktu i promienia na mapie, filtry lotów
  zgłoszonych (`CREATED`) i po czasie (`OVERDUE`), zmienne później przez Opcje.
- Snapshot REST co 5 minut plus strumień STOMP przez WebSocket na bieżąco.
  Bez konta i bez poświadczeń — oba kanały odpowiadają anonimowo.
- [Dokumentacja odtworzonego API](docs/API.md) z inżynierii wstecznej aplikacji
  `pl.pansa.dronetower` 1.1.12.

### Bezpieczeństwo

- Numery telefonów pilotów, obecne w odpowiedzi API, nie trafiają do żadnej encji
  ani zdarzenia. Pilnuje tego osobny test.

[1.0.2]: https://github.com/amuamurawski/DroneTower/releases/tag/v1.0.2
[1.0.1]: https://github.com/amuamurawski/DroneTower/releases/tag/v1.0.1
