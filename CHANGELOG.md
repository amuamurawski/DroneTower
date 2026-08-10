# Historia zmian

Format według [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/),
wersjonowanie według [SemVer](https://semver.org/lang/pl/).

## [1.0.1] — 2026-08-10

### Zmienione

- Opis urządzenia z angielskiego `DroneTower check-in feed` na
  **Monitor zgłoszonych lotów** — to ten napis widać w wierszu urządzenia.
- `documentation` i `issue_tracker` w manifeście wskazują istniejące repozytorium
  `amuamurawski/DroneTower`. Poprzednie adresy prowadziły donikąd, co blokowało
  walidację HACS.

### Dodane

- Ikona marki przygotowana pod zgłoszenie do `home-assistant/brands`
  (`brands/custom_integrations/dronetower_amu/`) wraz z generatorem
  `tools/make_icon.py`. Do czasu scalenia PR-a panel integracji pokazuje
  „icon not available" — tego nie da się obejść po stronie tego repozytorium.
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

[1.0.1]: https://github.com/amuamurawski/DroneTower/releases/tag/v1.0.1
