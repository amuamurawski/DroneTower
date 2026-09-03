// Helper testowy: wykonuje plik karty (KLASYCZNY skrypt przeglądarki, bez
// exportów) w node:vm z minimalnymi stubami DOM i udostępnia:
//   - klasy zarejestrowane przez customElements.define (registry / getClass),
//   - top-level funkcje i stałe skryptu przez eval w tym samym kontekście vm
//     (getFunction / run) — deklaracje `const`/`function` żyją w globalnym
//     zakresie leksykalnym kontekstu, więc są osiągalne po wykonaniu skryptu.
//
// Zero zależności npm — tylko node:fs, node:vm, node:path, node:url.

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const FRONTEND_DIR = path.resolve(
  HERE,
  "../../custom_components/dronetower_amu/frontend",
);

/** Minimalny element DOM: wystarczający dla renderu kart do stringów HTML. */
class StubElement {
  constructor(tagName = "div") {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.style = {}; // przyjmuje też przypisania .cssText
    this.attributes = {};
    this.innerHTML = "";
    this.textContent = "";
    this.isConnected = false;
    this.title = "";
  }
  // Jak w realnym DOM: przypisanie innerHTML zastępuje (czyści) dzieci —
  // bez tego _teardown() + ponowny _build() karty dublowałby elementy.
  get innerHTML() {
    return this._innerHTML ?? "";
  }
  set innerHTML(v) {
    this._innerHTML = String(v);
    this.children = [];
  }
  append(...nodes) {
    this.children.push(...nodes);
  }
  appendChild(node) {
    this.children.push(node);
    return node;
  }
  removeChild(node) {
    this.children = this.children.filter((c) => c !== node);
    return node;
  }
  setAttribute(name, value) {
    this.attributes[String(name)] = String(value);
  }
  getAttribute(name) {
    return Object.hasOwn(this.attributes, name) ? this.attributes[name] : null;
  }
  addEventListener() {}
  removeEventListener() {}
  dispatchEvent() {
    return true;
  }
  querySelector() {
    return null;
  }
  querySelectorAll() {
    return [];
  }
  getBoundingClientRect() {
    return { x: 0, y: 0, width: 0, height: 0, top: 0, left: 0, right: 0, bottom: 0 };
  }
}

/** HTMLElement ze stubem shadow DOM (innerHTML + memoizowane getElementById). */
class StubHTMLElement extends StubElement {
  attachShadow() {
    const byId = new Map();
    this.shadowRoot = {
      innerHTML: "",
      getElementById(id) {
        if (!byId.has(id)) byId.set(id, new StubElement("div"));
        return byId.get(id);
      },
    };
    return this.shadowRoot;
  }
}

class StubResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function makeDocument() {
  return {
    createElement: (tag) => new StubElement(tag),
    createTextNode: (text) => ({ textContent: String(text) }),
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener() {},
    removeEventListener() {},
    head: new StubElement("head"),
    body: new StubElement("body"),
  };
}

/**
 * Wczytuje i wykonuje plik karty w świeżym kontekście vm.
 *
 * @param {string} fileName nazwa pliku w frontend/ (np. "dronetower-map-card.js")
 *   albo ścieżka absolutna.
 * @returns {{
 *   registry: Map<string, Function>,
 *   getClass: (name: string) => Function | undefined,
 *   getFunction: (name: string) => any,
 *   run: (expr: string) => any,
 *   window: object,
 *   document: object,
 *   context: object,
 * }}
 */
export function loadCard(fileName) {
  const filePath = path.isAbsolute(fileName)
    ? fileName
    : path.join(FRONTEND_DIR, fileName);
  const code = readFileSync(filePath, "utf8");

  const registry = new Map();
  const documentStub = makeDocument();

  const sandbox = {
    console,
    document: documentStub,
    HTMLElement: StubHTMLElement,
    ResizeObserver: StubResizeObserver,
    customElements: {
      define(name, cls) {
        if (registry.has(name)) {
          throw new Error(`customElements.define: '${name}' already defined`);
        }
        registry.set(name, cls);
      },
      get(name) {
        return registry.get(name);
      },
    },
    // Timery celowo bezczynne — testy mają być deterministyczne.
    setTimeout: () => 0,
    clearTimeout: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
    requestAnimationFrame: () => 0,
    cancelAnimationFrame: () => {},
  };
  // `window` wskazuje na obiekt globalny kontekstu, jak w przeglądarce.
  sandbox.window = sandbox;
  sandbox.self = sandbox;
  sandbox.globalThis = sandbox;

  const context = vm.createContext(sandbox);
  vm.runInContext(code, context, { filename: filePath });

  return {
    registry,
    getClass: (name) => registry.get(name),
    // "Sprytne przechwycenie": top-level `function`/`const`/`let` klasycznego
    // skryptu pozostają widoczne w kontekście — czyste funkcje karty można
    // testować bez exportów. Zwraca undefined, gdy identyfikator nie istnieje.
    getFunction: (name) => {
      if (!/^[A-Za-z_$][\w$]*$/.test(name)) {
        throw new Error(`Invalid identifier: ${name}`);
      }
      return vm.runInContext(
        `typeof ${name} === "undefined" ? undefined : ${name}`,
        context,
      );
    },
    run: (expr) => vm.runInContext(expr, context),
    window: sandbox,
    document: documentStub,
    context,
  };
}
