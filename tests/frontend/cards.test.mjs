// Testy dymne kart Lovelace: skrypt się wykonuje, klasa rejestruje się w
// customElements, karta rejestruje się w window.customCards, a render przez
// publiczne API (setConfig / set hass) nie wybucha. Celowo minimalne —
// szczegóły renderu zmieniają się częściej niż kontrakt.

import test from "node:test";
import assert from "node:assert/strict";

import { loadCard } from "./load-card.mjs";

const HASS_STUB = {
  locale: { language: "pl" },
  states: {
    "binary_sensor.dronetower_drony_w_okolicy": {
      attributes: {
        monitored_latitude: 52.2297,
        monitored_longitude: 21.0122,
        radius_m: 5000,
        total_active_in_poland: 42,
        stream_connected: true,
        drones: [
          {
            id: "abc12345-6789",
            status: "ACTIVE",
            distance_to_area_m: 1234,
            max_height_m: 120,
            start: "2026-09-03T10:00:00+02:00",
            end: "2026-09-03T11:00:00+02:00",
            latitude: 52.23,
            longitude: 21.01,
          },
        ],
      },
    },
  },
};

test("karta listy: rejestracja i render przez publiczne API", () => {
  const card = loadCard("dronetower-surveillance-card.js");

  const Cls = card.getClass("dronetower-surveillance-card");
  assert.ok(Cls, "customElements.define nie zarejestrowało dronetower-surveillance-card");
  assert.ok(
    (card.window.customCards || []).some((c) => c.type === "custom:dronetower-surveillance-card" || c.type === "dronetower-surveillance-card"),
    "brak wpisu w window.customCards",
  );

  const el = card.run("new (customElements.get('dronetower-surveillance-card'))()");
  el.setConfig({});
  el.hass = HASS_STUB;
  const root = el.shadowRoot.getElementById("root");
  assert.ok(root.innerHTML.includes("w zasięgu"), "render nie zawiera nagłówka statystyk");
});

test("karta listy: esc escapuje HTML (jeśli funkcja istnieje)", (t) => {
  const card = loadCard("dronetower-surveillance-card.js");
  const esc = card.getFunction("esc");
  if (typeof esc !== "function") {
    t.skip("brak top-level funkcji esc — pomijam");
    return;
  }
  assert.equal(esc('<img src=x onerror="x">'), "&lt;img src=x onerror=&quot;x&quot;&gt;");
});

test("karta mapy: rejestracja i set hass bez wyjątku", () => {
  const card = loadCard("dronetower-map-card.js");

  const Cls = card.getClass("dronetower-map-card");
  assert.ok(Cls, "customElements.define nie zarejestrowało dronetower-map-card");
  assert.ok(
    (card.window.customCards || []).some((c) => c.type === "custom:dronetower-map-card" || c.type === "dronetower-map-card"),
    "brak wpisu w window.customCards",
  );

  const el = card.run("new (customElements.get('dronetower-map-card'))()");
  el.setConfig({ title: "Test" });
  // Bez window.L karta próbuje doładować Leaflet — stuby DOM na to pozwalają,
  // a render nie może rzucić wyjątku.
  el.hass = HASS_STUB;
  assert.ok(Number.isFinite(el.getCardSize()), "getCardSize nie zwraca liczby");
});
