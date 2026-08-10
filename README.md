# DroneTower-AMU dla Home Assistanta

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Validate](https://github.com/amuamurawski/DroneTower/actions/workflows/validate.yml/badge.svg)](https://github.com/amuamurawski/DroneTower/actions/workflows/validate.yml)
[![Tests](https://github.com/amuamurawski/DroneTower/actions/workflows/tests.yml/badge.svg)](https://github.com/amuamurawski/DroneTower/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Integracja pokazująca **zgłoszone loty dronów** wokół wskazanego punktu, na podstawie
publicznego API systemu DroneTower Polskiej Agencji Żeglugi Powietrznej.
Nie wymaga konta ani żadnych poświadczeń.

Repozytorium zawiera też [dokumentację inżynierii wstecznej](docs/API.md) aplikacji
mobilnej PANSA, z której odtworzono to API.

## Zanim zainstalujesz — co to naprawdę pokazuje

To jest ważne, żeby nie budować na tym fałszywych oczekiwań. Źródłem danych są
**deklaracje pilotów w systemie PANSA**, a nie fizyczna detekcja statków powietrznych:

- dron latający **bez zgłoszenia nie pojawi się tu w ogóle** — czyli akurat ten,
  o który zwykle chodzi, gdy ktoś pyta „co lata nad moim domem";
- pozycja to **środek zadeklarowanej strefy lotu** (promień zwykle 40–500 m),
  a nie pozycja drona;
- status `CREATED` znaczy tylko tyle, że ktoś zgłosił zamiar lotu.

Do faktycznego wykrywania tego, co lata w okolicy, służy **Remote ID** — odbiornik
BLE / Wi-Fi NAN, np. ESP32 z firmware [OpenDroneID](https://github.com/opendroneid),
wpięty do HA przez MQTT. Szczegóły w [sekcji 7 dokumentacji](docs/API.md).
Oba źródła się uzupełniają: PANSA mówi „kto się zgłosił", Remote ID „co faktycznie lata".

## Encje

| Encja | Opis |
| --- | --- |
| `binary_sensor.…_dron_w_poblizu` | `on`, gdy strefa zgłoszonego lotu sięga monitorowanego obszaru |
| `sensor.…_drony_w_zasiegu` | liczba takich zgłoszeń |
| `sensor.…_odleglosc_najblizszego_drona` | odległość do krawędzi najbliższej strefy lotu (m) |
| `sensor.…_aktywne_zgloszenia_w_polsce` | licznik krajowy (diagnostyczny, domyślnie wyłączony) |
| `geo_location.…` | znacznik na mapie HA dla każdego lotu w zasięgu |

Atrybuty `binary_sensor` zawierają listę `drones` ze szczegółami każdego zgłoszenia
(status, odległość, promień strefy, pułap, okno czasowe).

## Instalacja przez HACS

Repozytorium nie jest w domyślnym katalogu HACS, więc dodaj je jako własne źródło:

1. **HACS → Integracje → menu (⋮) → Własne repozytoria**
2. URL: `https://github.com/amuamurawski/DroneTower`, kategoria: **Integration**
3. Znajdź **DroneTower-AMU** na liście, zainstaluj i **zrestartuj Home Assistanta**
4. **Ustawienia → Urządzenia i usługi → Dodaj integrację → DroneTower-AMU**

<details>
<summary>Instalacja ręczna</summary>

Skopiuj katalog `custom_components/dronetower_amu` do `config/custom_components/`
w swojej instancji i zrestartuj Home Assistanta.
</details>

## Konfiguracja

W kreatorze wskazujesz punkt i promień na mapie (domyślnie lokalizacja domu i 5 km)
oraz decydujesz, czy liczyć:

- **loty zgłoszone, jeszcze nierozpoczęte** (`CREATED`) — domyślnie tak, bo to
  ostrzeżenie z wyprzedzeniem;
- **zgłoszenia po czasie** (`OVERDUE`) — domyślnie nie, bo w praktyce to najczęściej
  zgłoszenia, których pilot zapomniał zamknąć (w badanej próbce 48 z 315).

Wszystko można później zmienić przez **Opcje**, bez usuwania integracji.

## Zdarzenia do automatyzacji

| Zdarzenie | Dane |
| --- | --- |
| `dronetower_amu_drone_detected` | pełne dane zgłoszenia, które właśnie weszło w zasięg |
| `dronetower_amu_drone_cleared` | `id` zgłoszenia, które opuściło zasięg |

Zapowiedź na głośniku, gdy pierwszy dron wejdzie w zasięg:

```yaml
automation:
  - alias: "Zapowiedź: dron w okolicy"
    mode: single
    triggers:
      - trigger: state
        entity_id: binary_sensor.drony_w_okolicy_dron_w_poblizu
        from: "off"
        to: "on"
    conditions:
      - condition: time
        after: "07:00:00"
        before: "22:00:00"
    actions:
      - action: tts.speak
        target:
          entity_id: tts.piper
        data:
          media_player_entity_id: media_player.salon
          cache: false
          message: >-
            {% set drony = state_attr('binary_sensor.drony_w_okolicy_dron_w_poblizu', 'drones') %}
            {% set d = (drony or [])[0] | default(none) %}
            {% if d %}
              {% set m = d.distance_to_area_m %}
              Uwaga. Zgłoszono lot drona
              {{ 'mniej niż sto' if m < 100 else ((m / 100) | round | int) * 100 }}
              metrów stąd, na wysokości do {{ d.max_height_m }} metrów.
            {% endif %}
```

Identyfikatory encji i silnika TTS podmień na swoje — jak je znaleźć oraz warianty
(powiadomienie na telefon, zapowiedź per dron, podbicie głośności, karta na mapę)
opisałem w [docs/automatyzacje.md](docs/automatyzacje.md).

## Jak to działa

Przy starcie pobierany jest snapshot `GET /api/checkins`, a potem integracja
subskrybuje krajowy broadcast STOMP przez WebSocket i aktualizuje stan na bieżąco.
Snapshot powtarza się co 5 minut, żeby wyrównać ewentualne rozjazdy.

Ponieważ krajowy strumień to około jedno zdarzenie na sekundę, encje odświeżają się
tylko wtedy, gdy zmieni się zbiór lotów w Twoim zasięgu — inaczej baza recordera
rosłaby bez powodu. Znaczniki na mapie celowo nie mają `unique_id`, żeby każdy
przelatujący dron nie zostawiał po sobie wpisu w rejestrze encji.

## Prywatność

Odpowiedź API zawiera numer telefonu pilota, jeśli ten zgodził się na publikację.
Integracja **celowo nie zapisuje ani nie wystawia numerów telefonu** w żadnej encji
ani zdarzeniu — pilnuje tego osobny test. Jeśli będziesz modyfikować kod, zostaw to tak.

## Rozwój

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m pytest

# Test na żywo przeciwko produkcyjnemu API (lat lon promień_w_metrach):
.venv/bin/python tools/live_check.py 52.2297 21.0122 15000
```

Aplikacja mobilna PANSA nie jest częścią tego repozytorium — jej redystrybucja nie
należy do nas. `docs/API.md` opisuje, jak odtworzyć analizę z paczki pobranej
samodzielnie.

## Zastrzeżenia

Projekt nieoficjalny, niezwiązany z PANSA. Adresy i model danych odtworzono z wersji
1.1.12 aplikacji DroneTower i mogą się zmienić bez ostrzeżenia. Dane służą wyłącznie
do orientacji sytuacyjnej — **nie są źródłem informacji lotniczej** i nie zastępują
oficjalnych kanałów PANSA.

## Licencja

[MIT](LICENSE)
