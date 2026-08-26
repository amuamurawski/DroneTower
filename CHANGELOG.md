# Historia zmian

Format według [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/),
wersjonowanie według [SemVer](https://semver.org/lang/pl/).

## [1.2.1] — 2026-08-26

### Naprawione

- **Sensor „Powracający operatorzy" nie miał ikony.** Użyłem nazwy
  `mdi:account-repeat`, która nie istnieje w zestawie Material Design Icons —
  a nieistniejąca nazwa nie daje błędu ani ikony zastępczej, tylko puste miejsce.
  Zamieniona na `mdi:account-reactivate`.

### Dodane

- `tools/check_icons.py` — sprawdza wszystkie nazwy `mdi:` w kodzie wobec
  oficjalnego indeksu MDI. Wymaga sieci, więc jest skryptem deweloperskim,
  a nie zadaniem CI.

## [1.2.0] — 2026-08-12

### Dodane

- **Sensor „Ostatni przelot”.** Stan to czas ostatniego przelotu, a atrybuty niosą
  komplet: identyfikator zgłoszenia, odległość najbliższego zbliżenia i do środka
  strefy, współrzędne, promień strefy, pułap, okno czasowe, status, typ i kanał
  zgłoszenia, liczbę wejść w zasięg oraz dane operatora — pseudonim, liczba jego
  lotów, kiedy był poprzednio, jak blisko i czy to powrót.

### Zmienione

- **Numer telefonu trafia teraz także do atrybutów tego sensora**, gdy włączony jest
  zapis numerów. To świadoma zmiana granicy z 1.1.0, gdzie numer wychodził wyłącznie
  przez akcję `get_operator`.

  **Jeśli miałeś już włączony zapis numerów, przeczytaj to przed aktualizacją.**
  Atrybuty encji zapisują się do bazy recordera przy każdej zmianie stanu i zostają
  tam na czas jej retencji, trafiają też do kopii zapasowych. Wyłączenie opcji kasuje
  numery z historii integracji, ale **nie usuwa ich z bazy recordera** — tam trzeba
  je wyczyścić osobno. Jeśli nie chcesz tego efektu, wyłącz opcję *przed*
  aktualizacją.

  Co zostaje bez zmian: numer nadal **nie trafia do żadnego zdarzenia integracji**
  (`drone_detected`, `drone_cleared`, `known_operator` niosą tylko solony pseudonim),
  ani do rekordów lotów, podsumowań operatorów czy akcji `get_history`.

## [1.1.0] — 2026-08-12

### Dodane

- **Lokalna historia przelotów.** Każdy lot, który wszedł w monitorowany obszar,
  zapisuje się w `.storage` (osobno od bazy recordera, więc przeżywa jej czyszczenie):
  czas, najbliższe zbliżenie, pułap, okno czasowe. Retencja 365 dni, do zmiany
  w Opcjach. Rekordy lotów są **wolne od danych osobowych z samej konstrukcji** —
  niosą wyłącznie solony pseudonim operatora.
- **Rozpoznawanie powracających operatorów** i zdarzenie
  `dronetower_amu_known_operator` przy drugim i kolejnym locie tej samej osoby.
  Uwaga na ograniczenie źródła: numer telefonu jest jedynym identyfikatorem
  łączącym loty tej samej osoby, a publikuje go tylko około jednej trzeciej
  zgłoszeń — licznik powracających jest dolnym oszacowaniem.
- **Cztery akcje**: `get_history`, `get_operators`, `get_operator`, `purge_history`.
  Numer telefonu zwraca **wyłącznie** `get_operator` — przeglądanie historii nigdy
  go nie ujawnia, bo odpowiedź akcji łatwo wpada do sensora szablonowego, a stamtąd
  do bazy recordera.
- Dwa sensory: **Powracający operatorzy** oraz diagnostyczny **Przeloty w ostatnich
  30 dniach**. Bez atrybutów listowych, żeby nie obciążać recordera.
- Opcja **Zapisuj numery telefonów pilotów**, domyślnie wyłączona. Jej wyłączenie
  kasuje numery zebrane wcześniej.
- `diagnostics.py` — same liczniki, z redakcją współrzędnych domu i soli.

### Naprawione

- Historia mogła zginąć przy zmianie opcji. Przeładowanie wpisu tworzy nowy `Store`,
  który nie wie o opóźnionym zapisie poprzedniej instancji, więc dane czekające na
  zapis czytało się z powrotem jako nieaktualne. Wpis zapisuje się teraz twardo
  przed wyładowaniem.

## [1.0.3] — 2026-08-10

### Naprawione

- **Pętla ponownych połączeń mogła się kręcić bez końca.** Backoff był zerowany przy
  każdym udanym CONNECT, więc gniazdo, które nawiązuje połączenie i natychmiast je
  zrywa, powodowało w kółko: połącz → zerwij → odczekaj 5 s → **pełny pobór REST
  (~140 kB, ~300 obiektów)** → połącz. Bez rosnącego odstępu i bez końca. Teraz
  backoff zeruje wyłącznie sesja, która utrzymała się co najmniej 60 s, a
  synchronizacja REST po zerwaniu następuje tylko wtedy, gdy strumień faktycznie
  działał — nieudana próba połączenia nie wnosi nic nowego o liście zgłoszeń.

### Zmienione

- **Obsługa zdarzenia jest ~160x tańsza.** Krajowy broadcast to około jedno
  zdarzenie na sekundę, a każde z nich powodowało wcześniej ponowne sparsowanie dat
  i przeliczenie odległości geodezyjnej dla **wszystkich** zgłoszeń w Polsce.
  Zmierzone 2,99 ms na zdarzenie, czyli ok. 258 s czasu CPU na dobę. Teraz każde
  zgłoszenie jest parsowane i mierzone raz, przy nadejściu, a zdarzenie dotyka
  wyłącznie rekordu, którego dotyczy: 0,018 ms i ok. 2 s CPU na dobę.
  Pomiar odtworzysz przez `tools/bench_build.py`.

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

[1.2.1]: https://github.com/amuamurawski/DroneTower/releases/tag/v1.2.1
[1.2.0]: https://github.com/amuamurawski/DroneTower/releases/tag/v1.2.0
[1.1.0]: https://github.com/amuamurawski/DroneTower/releases/tag/v1.1.0
[1.0.3]: https://github.com/amuamurawski/DroneTower/releases/tag/v1.0.3
[1.0.2]: https://github.com/amuamurawski/DroneTower/releases/tag/v1.0.2
[1.0.1]: https://github.com/amuamurawski/DroneTower/releases/tag/v1.0.1
