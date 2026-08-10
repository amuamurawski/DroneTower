# Automatyzacje

## Zanim wkleisz cokolwiek — sprawdź dwie nazwy

Poniższe przykłady używają identyfikatorów z mojej instalacji. U Ciebie będą inne,
bo powstają z nazwy, którą nadałeś integracji przy dodawaniu.

**Encja czujnika.** Narzędzia deweloperskie → Stany → wpisz `dron`. Szukasz czegoś
w rodzaju `binary_sensor.drony_w_okolicy_dron_w_poblizu`. Podmień to w przykładach.

**Encja TTS.** Narzędzia deweloperskie → Akcje → `tts.speak` → pole *Cel*. Zobaczysz
listę dostępnych silników mowy. Typowo jedno z:

| Silnik | Encja |
| --- | --- |
| Home Assistant Cloud (Nabu Casa) | `tts.home_assistant_cloud` |
| Piper (lokalny, Voice PE / add-on) | `tts.piper` |
| Google Translate | `tts.google_en_com` lub `tts.google_translate_pl_pl` |

Jeśli używasz Google Translate, upewnij się, że w konfiguracji silnika język jest
ustawiony na polski — inaczej przeczyta polski tekst z angielską wymową.

## Zapowiedź na głośniku (podstawowa)

Wyzwala się, gdy czujnik przechodzi z `off` na `on`, czyli gdy **pojawia się
pierwszy** dron w zasięgu. Kolejne drony w tym samym czasie nie wywołają zapowiedzi
— jeśli chcesz inaczej, patrz wariant „każdy dron osobno" niżej.

```yaml
automation:
  - alias: "Zapowiedź: dron w okolicy"
    id: dronetower_zapowiedz_glosnik
    mode: single
    triggers:
      - trigger: state
        entity_id: binary_sensor.drony_w_okolicy_dron_w_poblizu
        from: "off"
        to: "on"
    conditions:
      # Cisza nocna — bez tego obudzi Cię zgłoszenie o trzeciej nad ranem.
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

`cache: false` jest istotne — komunikat za każdym razem zawiera inną odległość,
a domyślne cache'owanie TTS potrafi odtworzyć poprzednie nagranie.

## Wariant: każdy dron osobno

Zdarzenie `dronetower_amu_drone_detected` leci raz na każde zgłoszenie wchodzące
w zasięg, więc daje dokładniejszy obraz kosztem gadatliwości. `mode: queued`
sprawia, że przy dwóch dronach naraz zapowiedzi ustawią się w kolejce zamiast się
zagłuszyć albo zgubić.

```yaml
automation:
  - alias: "Zapowiedź: każdy zgłoszony dron"
    id: dronetower_zapowiedz_kazdy
    mode: queued
    max: 5
    triggers:
      - trigger: event
        event_type: dronetower_amu_drone_detected
    conditions:
      - condition: template
        value_template: "{{ trigger.event.data.distance_to_area_m < 1500 }}"
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
            {% set m = trigger.event.data.distance_to_area_m %}
            Dron {{ 'mniej niż sto' if m < 100 else ((m / 100) | round | int) * 100 }}
            metrów stąd, do {{ trigger.event.data.max_height_m }} metrów wysokości.
```

## Wariant: zapowiedź plus powiadomienie na telefon

```yaml
    actions:
      - parallel:
          - action: tts.speak
            target:
              entity_id: tts.piper
            data:
              media_player_entity_id: media_player.salon
              cache: false
              message: "Uwaga, zgłoszony lot drona w okolicy."
          - action: notify.mobile_app_telefon
            data:
              title: Dron w okolicy
              message: >-
                {{ trigger.event.data.distance_to_area_m }} m stąd,
                do {{ trigger.event.data.max_height_m }} m AGL,
                do {{ as_timestamp(trigger.event.data.end) | timestamp_custom('%H:%M') }}.
              data:
                # Otwiera mapę HA po tapnięciu w powiadomienie.
                clickAction: /lovelace/mapa
```

## Wariant: podbicie głośności na czas zapowiedzi

Przydatne, jeśli głośnik zwykle stoi cicho.

```yaml
    actions:
      - variables:
          poprzednia: "{{ state_attr('media_player.salon', 'volume_level') }}"
      - action: media_player.volume_set
        target:
          entity_id: media_player.salon
        data:
          volume_level: 0.6
      - action: tts.speak
        target:
          entity_id: tts.piper
        data:
          media_player_entity_id: media_player.salon
          cache: false
          message: "Uwaga, zgłoszony lot drona w okolicy."
      - delay: "00:00:08"
      - action: media_player.volume_set
        target:
          entity_id: media_player.salon
        data:
          volume_level: "{{ poprzednia }}"
```

`tts.speak` wraca od razu po rozpoczęciu odtwarzania, a nie po jego zakończeniu —
stąd `delay` przed przywróceniem głośności. Dobierz go do długości komunikatu.

## Karta na pulpit

```yaml
type: entities
title: Drony w okolicy
entities:
  - entity: binary_sensor.drony_w_okolicy_dron_w_poblizu
  - entity: sensor.drony_w_okolicy_drony_w_zasiegu
  - entity: sensor.drony_w_okolicy_odleglosc_najblizszego_drona
```

Do mapy użyj standardowej karty `map` i dodaj `geo_location_sources`:

```yaml
type: map
geo_location_sources:
  - dronetower_amu
entities:
  - zone.home
hours_to_show: 0
```

## Uwaga na fałszywe poczucie bezpieczeństwa

Cisza tej automatyzacji nie znaczy, że nad domem nic nie lata — znaczy tylko tyle,
że nikt nie zgłosił lotu w systemie PANSA. Powody opisałem w
[sekcji 7 dokumentacji API](API.md).
