# DroneTower (PANSA) — dokumentacja API z inżynierii wstecznej

Wynik analizy `DroneTower_1.1.12_APKPure.xapk` (`pl.pansa.dronetower`, versionCode 124).

## 1. Czym jest ta aplikacja

DroneTower to oficjalna aplikacja Polskiej Agencji Żeglugi Powietrznej (PANSA)
służąca do zgłaszania lotów dronem (*check-in*) w systemie PansaUTM. Aplikacja jest
**hybrydowa (Capacitor + Angular)** — cała logika biznesowa leży w bundlu JavaScript
w `assets/public/`, a nie w kodzie Java/Kotlin. `classes.dex` zawiera wyłącznie
runtime Capacitora, Firebase i Google Play Services, więc dekompilacja jadx-em nie
była potrzebna.

Konsekwencja praktyczna dla Twojego celu: **aplikacja nie odbiera Remote ID**.
W manifeście nie ma żadnych uprawnień Bluetooth ani Wi-Fi scan — tylko `INTERNET`,
`ACCESS_FINE_LOCATION` i push. Wszystkie dane o dronach pochodzą z serwera PANSA,
a nie z nasłuchu radiowego w okolicy. Szerzej o tym w sekcji 7.

## 2. Konfiguracja runtime

Aplikacja pobiera konfigurację ze statycznego pliku dołączonego do paczki,
`assets/public/assets/dynamic.config.json`:

```json
{
  "apiDomain": "bff-drone-tower.uav.pansa.pl",
  "environment": "prod",
  "pansaUtmLoginUrl": "https://utm.pansa.pl/#/login",
  "pansaUtmRegisterUrl": "https://utm.pansa.pl/#/register",
  "version": "20260206091915-1.0.0"
}
```

Z `apiDomain` budowane są dwa adresy bazowe:

| Rzecz | Wartość |
| --- | --- |
| REST | `https://bff-drone-tower.uav.pansa.pl/api` |
| WebSocket (STOMP) | `wss://bff-drone-tower.uav.pansa.pl/ws` |

Backend to BFF (Backend For Frontend) stojący przed właściwym PansaUTM.

## 3. Wymagany nagłówek `content-type`

To jest najważniejszy szczegół, bez którego nic nie zadziała. Interceptor HTTP
aplikacji ustawia własny vendor media type na **każdym** żądaniu, również na GET-ach
bez ciała:

```
content-type: application/vnd.pansa.bff-drone-tower.v1+json
```

Wersja `v2` (`...bff-drone-tower.v2+json`) jest używana warunkowo, gdy w
`/api/capabilities` włączona jest flaga `V2api`.

Bez tego nagłówka serwer odpowiada **HTTP 415 Unsupported Media Type** z pustym
ciałem — co łatwo pomylić z blokadą.

## 4. Uwierzytelnianie

Logowanie: `POST /api/auth` z ciałem `{ ...credentials, deviceInfo: { firebaseToken,
manufacturer, model, systemName, systemVersion } }`; odpowiedź zawiera m.in. `userId`
i token dostępowy, wysyłany potem jako `Authorization: Bearer <token>`.

Interceptor dokłada token **tylko** dla ścieżek pasujących do:
`checkins`, `checkin-archives`, `pilot` (poza `password-recovery`), `missions`.
Reszta endpointów jest projektowo anonimowa.

**Weryfikacja na żywo (2026-08-10): `GET /api/checkins` zwraca HTTP 200 również bez
nagłówka `Authorization`.** Klient dokłada token, ale serwer go nie egzekwuje dla
odczytu listy aktywnych zgłoszeń. Analogicznie WebSocket przyjmuje anonimowe
`CONNECT`. Dla integracji z Home Assistant oznacza to, że **nie potrzebujesz konta
ani żadnych poświadczeń** — i nie musisz automatyzować logowania.

## 5. Endpoint kluczowy: `GET /api/checkins`

Zwraca wszystkie aktywne zgłoszenia lotów w Polsce (w teście: 285 pozycji, ~140 kB).

```json
{
  "userCheckin": null,
  "checkins": [
    {
      "id": "7f3aade4-c712-48cf-ba9e-7b29ed313689",
      "status": "ACTIVE",
      "pilotPhoneNumber": { "countryCode": "PL", "number": "789767678" },
      "phoneNumberPublicationConsent": true,
      "startDateTime": "2026-08-10T16:21:45.061Z",
      "endDateTime": "2026-08-10T16:51:45.061Z",
      "flightArea": {
        "maxHeight": 120,
        "center": { "latitude": 50.4377960833333, "longitude": 16.6502777 },
        "radius": 100.0
      },
      "missionArea": [],
      "supervision": false,
      "messageToAnsp": "",
      "missionFinished": false,
      "fromMissionPlanner": false,
      "checkinType": "STANDARD",
      "origin": "DT"
    }
  ]
}
```

Uwagi do modelu, wynikające z obserwacji rzeczywistych danych:

- `flightArea.center` jest zawsze obecne; `flightArea.radius` bywa `null`
  (3 z 285 rekordów) — w kodzie traktuj to jako punkt.
- `flightArea.radius` w metrach, zakres w próbce 40–500 m.
- `flightArea.maxHeight` w metrach AGL, zakres 5–120 m.
- `missionArea` to lista poligonów GeoJSON (`type: "Polygon"`) dla lotów BVLOS
  planowanych w Mission Plannerze; dla zwykłych check-inów pusta lista lub `null`.
- `status`: `CREATED` (zgłoszony, przed startem), `ACTIVE` (w powietrzu),
  `OVERDUE` (minął `endDateTime`, pilot nie zamknął zgłoszenia), `FINISHED`.
  Kod aplikacji zna dodatkowo `ACCEPTED`, `ATC_MODIFIED`, `LAND_NOW`, `REJECTED`
  — te dotyczą lotów w strefach kontrolowanych.
- `origin`: `DT` (DroneTower) lub `FC` (inny kanał zgłoszeń).
- `pilotPhoneNumber` jest wypełniony tylko przy `phoneNumberPublicationConsent: true`.
  To dane osobowe — patrz sekcja 8.

## 6. Strumień na żywo: STOMP over WebSocket

Aplikacja używa `@stomp/rx-stomp` z surowym WebSocketem. Funkcja `beforeConnect`
jest pusta — **żadne nagłówki autoryzacji nie są dokładane do ramki CONNECT**.

```
URL:         wss://bff-drone-tower.uav.pansa.pl/ws
subprotocol: v12.stomp (negocjowany; oferowane v12/v11/v10)
```

Handshake (ramki STOMP rozdzielane bajtem `NUL`, `0x00`):

```
CONNECT
accept-version:1.0,1.1,1.2
heart-beat:10000,10000

^@
```

Odpowiedź serwera: `CONNECTED / version:1.2 / heart-beat:5000,5000`.

Dwa tematy, oba z konfiguracji aplikacji:

| Nazwa w kodzie | Destination |
| --- | --- |
| `activeCheckinsTopicName` | `/websocket/topic/drone-tower-queue/drone-tower-active-checkins-topic/broadcast` |
| `alertTopicName` | `/websocket/topic/drone-tower-queue/drone-tower-geospace-topic/Receivers` |

Subskrypcja:

```
SUBSCRIBE
id:sub-0
destination:/websocket/topic/drone-tower-queue/drone-tower-active-checkins-topic/broadcast

^@
```

Typ zdarzenia przychodzi w **nagłówku STOMP `event-type`**, nie w ciele:
`CheckinEvent`, `CheckinFinishedEvent`, `CheckinLostControlEvent`,
`CheckinRefreshEvent`. Na temacie alertów: `NewAlertEvent`
(ciało zawiera `alertId` i `endTime`).

Ciało wiadomości opakowuje pojedynczy check-in:

```json
{ "checkin": { "id": "...", "status": "ACTIVE", "flightArea": { ... } } }
```

Obciążenie strumienia zmierzone w praktyce: **42 zdarzenia w 45 sekund**
dla całego kraju, więc filtrowanie po odległości musi się dziać po stronie klienta.

## 7. Czego tu nie ma — i co to znaczy dla wykrywania dronów

Warto to powiedzieć wprost, zanim zbudujesz coś na fałszywym założeniu.

Ten kanał danych pokazuje **deklaracje pilotów**, a nie fizycznie wykryte statki
powietrzne. Wynikają z tego trzy ograniczenia:

1. **Dron widoczny ≠ dron w powietrzu.** `CREATED` znaczy tylko tyle, że ktoś
   zgłosił zamiar lotu na najbliższe pół godziny. `OVERDUE` to najczęściej
   zgłoszenie, którego pilot zapomniał zamknąć — w próbce było ich 50 z 285.
2. **Dron w powietrzu ≠ dron widoczny.** Loty poniżej progu obowiązku zgłoszenia,
   loty niezgłoszone i wszystko, co lata bezprawnie, nie pojawi się tutaj w ogóle.
   Dla „nieproszonego" drona nad ogrodem ten kanał jest z definicji ślepy.
3. **Pozycja to środek strefy, nie pozycja drona.** Dostajesz okrąg o promieniu
   40–500 m, w którym lot się odbywa, aktualizowany zdarzeniami o zmianie statusu —
   a nie telemetrię pozycji.

Jeśli zależy Ci na faktycznym wykrywaniu tego, co lata nad domem, właściwą
technologią jest **Remote ID** (rozporządzenie UE 2019/945 — drony klasy C1–C3
nadają identyfikator, pozycję i pozycję pilota przez Bluetooth LE / Wi-Fi NAN).
Odbiera się to lokalnie, tanim odbiornikiem, np. ESP32 z firmware
[OpenDroneID](https://github.com/opendroneid) albo projektem
[Drone Remote ID Scanner](https://github.com/alphafox02/DroneID) — i wpina do Home
Assistanta przez MQTT lub ESPHome. To dwa uzupełniające się źródła: PANSA mówi
„kto się zgłosił", Remote ID mówi „co faktycznie lata".

## 8. Kwestie prawne i higiena korzystania

Kilka rzeczy, o których warto wiedzieć, zanim to postawisz na stałe:

- **Dekompilacja w celu interoperacyjności** jest dozwolona — art. 75 ust. 2 pkt 3
  ustawy o prawie autorskim (implementacja art. 6 dyrektywy 2009/24/WE). Napisanie
  własnego klienta do publicznego API mieści się w tym wyjątku.
- **Regulamin aplikacji** ([PANSA](https://www.pansa.pl/wp-content/uploads/2024/01/Regulamin-aplikacji-DroneTower.pdf))
  reguluje korzystanie z aplikacji; własny klient działa poza nim. Użytek osobisty
  do świadomości sytuacyjnej wokół własnego domu to niekontrowersyjny scenariusz,
  ale nie redystrybuuj tych danych ani nie buduj na nich usługi publicznej bez
  kontaktu z PANSA.
- **Dane osobowe.** `pilotPhoneNumber` to numer telefonu konkretnej osoby.
  Publikacja za zgodą pilota dotyczy kontaktu w sprawach ruchu lotniczego, a nie
  dowolnego dalszego przetwarzania. Integracja w tym repo **domyślnie nie zapisuje
  numerów**; zapis jest osobną opcją, a gdy jest włączony, numer nie trafia do
  żadnej encji, atrybutu ani zdarzenia — leży raz na osobę w `.storage` i wychodzi
  wyłącznie przez akcję `get_operator`. Rekordy lotów niosą tylko solony pseudonim.
  Jeśli będziesz to zmieniać, zachowaj tę granicę: to ona sprawia, że numery nie
  utrwalają się w bazie recordera.
- **Rate limiting istnieje** — interceptor obsługuje HTTP 429. Snapshot REST co
  kilka minut plus WebSocket do zmian to wzorzec, który aplikacja sama stosuje;
  trzymaj się go i nie odpytuj REST-a w pętli.
- Adresy i model danych pochodzą z wersji 1.1.12 i mogą się zmienić bez ostrzeżenia.

## 9. Pozostałe endpointy (dla kompletności)

Wszystkie względem `https://bff-drone-tower.uav.pansa.pl/api`.

| Endpoint | Metoda | Auth | Opis |
| --- | --- | --- | --- |
| `/capabilities` | GET | nie | Kategorie lotów, flagi funkcji, `geoserverUrl`, style kafelków |
| `/checkins` | GET | nie* | Aktywne zgłoszenia lotów (sekcja 5) |
| `/checkins/` | POST | tak | Utworzenie zgłoszenia |
| `/checkins/{id}` | DELETE | tak | Zamknięcie zgłoszenia (`?final=`) |
| `/checkins/{id}/lost-control` | POST | tak | Zgłoszenie utraty kontroli |
| `/checkin-archives` | GET | tak | Historia zgłoszeń pilota |
| `/missions/` | GET | tak | Lista misji BVLOS |
| `/flight-conditions/status` | POST | nie | Status strefy dla punktu: `status`, `kpIndexDetails`, `elevationDetails` |
| `/flight-conditions/details` | POST | nie | Szczegóły: kolidujące strefy, pogoda, czy wymagana misja |
| `/flight-conditions/airspace-elements/reservations` | POST | nie | Rezerwacje elementów przestrzeni |
| `/geocode` | GET | nie | Wyszukiwanie miejsc |
| `/system/translations/{locale}` | GET | nie | Tłumaczenia systemowe |
| `/auth` | POST | — | Logowanie (sekcja 4) |
| `/enrollment/*` | POST | nie | Rejestracja konta |
| `/pilot/*` | GET/POST | tak | Profil pilota |

Statusy stref w `flight-conditions`: `NO_RESTRICTION`, `NO_RESTRICTION_INFO`,
`CONDITIONAL`, `PROHIBITED`.

\* Klient dokłada token, serwer go nie wymaga — patrz sekcja 4.

## 10. Jak to odtworzyć

```bash
unzip -q DroneTower_1.1.12_APKPure.xapk -d extracted_xapk
unzip -q extracted_xapk/pl.pansa.dronetower.apk -d work/base_apk
cat work/base_apk/assets/public/assets/dynamic.config.json

# Endpointy i model danych są w bundlu Angulara:
grep -o 'authenticationEndpoint.\{0,4000\}' \
  work/base_apk/assets/public/main.*.js

# Test REST:
curl -H 'content-type: application/vnd.pansa.bff-drone-tower.v1+json' \
  https://bff-drone-tower.uav.pansa.pl/api/checkins | jq '.checkins | length'
```

Skrypty użyte w analizie leżą w [`tools/`](../tools/):

| Skrypt | Do czego |
| --- | --- |
| `ctx.py` | kontekst wokół dopasowania regex w zminifikowanym bundlu (grep tu nie pomoże — cały plik to jedna linia) |
| `slice.py` | wycinek pliku po offsetach, gdy pozycja jest już znana |
| `wstest.mjs` | surowy klient STOMP, wypisuje nieprzetworzone ramki (Node 22+) |
| `live_check.py` | test klienta integracji przeciwko produkcji: snapshot, filtr odległości i strumień na żywo |

Sama aplikacja mobilna nie jest częścią repozytorium — jej redystrybucja nie należy
do nas. Paczkę trzeba pobrać samodzielnie.
