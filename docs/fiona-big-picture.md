# Fiona v1.0 – KI-gestütztes Breakout & EIA Trading-System (Big Picture)

## Ziel

Aufbau eines KI-gestützten Trading-Systems („Fiona v1.0“) für den Handel von **Breakouts** und **EIA-Setups** in Öl, mit:

- klar definierten, regelbasierten Strategiemodulen
- deterministischer Risk Engine (kein Overrulen durch KI)
- KI-Unterstützung (lokales LLM + GPT-Reflexion) für Bewertung/Begründung
- Shadow-Trading zum Lernen ohne Kapitalrisiko
- Weaviate als Wissensspeicher für Trades, Reasoning und Nachbetrachtung
- (zunächst) **nur Empfehlungen**, keine Auto-Execution

Der Fokus liegt auf **Robustheit, Nachvollziehbarkeit und Lernfähigkeit**, nicht auf HFT oder News-Trading.

---

## Grobe Architektur

**Core-Komponenten:**

1. **Broker Service (XTB)**
   - Anbindung an XTB (Preisfeed, Kontostand, Positionen, Orders)
   - Normalisierung der Daten für das System

2. **Market Data + Phase Engine**
   - Aggregation von Candles (1m/5m/15m)
   - Bestimmung von Sessions/Phasen:
     - ASIA_RANGE, LONDON_CORE, US_CORE, EIA_WINDOW, FRIDAY_LATE, etc.
   - Berechnung von Kennzahlen (ATR, VWAP, Trend-Bias, Asia-Range, London-High/Low)

3. **Strategy Engine (Breakout + EIA)**
   - Regelbasierte Erkennung von Setup-Kandidaten:
     - Asia/London-Breakouts
     - US-Core-Breakouts
     - EIA-Reversion & EIA-Trend-Day
   - Liefert `SetupCandidate`-Objekte mit allen relevanten Daten

4. **KI-Schicht (lokales LLM + GPT-Reflexion)**
   - Lokales LLM (z. B. Gemma 3 12B) bewertet `SetupCandidate`s:
     - Entscheidung `TAKE` / `SKIP`
     - konkreter Entry/SL/TP-Plan
     - textuelle Begründung („warum ist der Trade sinnvoll?“)
   - GPT-4.x reflektiert:
     - prüft Logik und Regelkonformität
     - passt ggf. Parameter an
     - vergibt Score (z. B. 0–100) + Begründung

5. **Risk Engine (deterministisch)**
   - kennt Kontostand, Tages-/Wochen-PnL, offene Risiken
   - setzt harte Grenzen:
     - max. Risiko/Trade
     - max. Tages-/Wochenverlust
     - max. offene Risiken
     - Sperrzeiten (EIA-Fenster, News, Overnight, Freitag-Cutoff)
   - entscheidet final:
     - `allowed = true/false`
     - Positionsgröße in Kontrakten

6. **Execution Layer**
   - erzeugt **Live-Empfehlungen** für den User (Entry/SL/TP + Begründung)
   - (später optional: Auto-Execution über XTB)

7. **Shadow Trader**
   - führt Trades „verdeckt“ auf einem virtuellen Konto aus, auch wenn Risk Engine live blockiert
   - nutzt dieselben Strategien und KI-Pläne
   - loggt Ergebnisse („was wäre gewesen, wenn…?“) zur Optimierung

8. **Weaviate / Storage**
   - speichert pro Trade ein `TradeCase`-Objekt mit:
     - Markt-Kontext / Phase
     - Setup-Daten
     - Gemma-Reasoning
     - GPT-Reflexion + Score
     - Entry/SL/TP
     - reales Ergebnis (PnL, R-Multiple)
     - 5–10-Minuten-Nachbetrachtung nach Exit
   - dient als Wissensbasis für spätere Analysen und Optimierungen (z. B. bessere TP/SL-Logik)

9. **UI / Fiona-Frontend**
   - zeigt:
     - aktuelle Phase + Marktübersicht
     - genehmigte Setups (mit Begründung)
     - Risk-Status (z. B. „Handel heute gesperrt“)
     - Live-Positionen
     - Historie inkl. KI-Reasoning
     - Shadow-Analyse (optional)

---

## Wichtige Prinzipien

- **Preis vor News:**  
  Nachrichten werden NICHT gehandelt, nur die Preisreaktion (Breakouts/EIA-Candles).  
  News dienen nur für Sperrfenster (z. B. EIA-Zeiten, High-Impact-Events).

- **Deterministische Risk Engine:**  
  KI darf nie Risk-Limits überschreiben, nur Vorschläge machen.  
  Risk Engine hat das letzte Wort.

- **KI als „Berater“, nicht als „Gott“:**  
  - Lokales LLM: bewertet Setups, erstellt Plan + Begründung.  
  - GPT-Reflexion: Quality-Check, Score, eventuelle Anpassung.  
  - Beide schreiben ihre Begründung ins `TradeCase`.

- **Shadow-Trading immer aktiv:**  
  - auch bei gesperrtem Live-Handel  
  - sammelt Lernmaterial für spätere Optimierungen

---

## Erste Implementierungsziele (grobe Checkliste)

- [ ] Projektgrundstruktur für Fiona v1.0 anlegen (Backend + einfache UI)
- [ ] XTB Broker Service: Verbindung, Account-Abfrage, Preisfeed
- [ ] Candles + MarketState Aggregation
- [ ] Phase Engine (Sessions, EIA-Fenster, Freitag-Cutoff)
- [ ] Strategy Engine V1: Breakout + EIA SetupCandidate-Erkennung
- [ ] KiGate-Connector für lokales LLM (Gemma) + GPT-Reflexion
- [ ] Risk Engine V1 (deterministische Regeln, konfigurierbar via YAML)
- [ ] Shadow Trader (virtuelles Konto, Logging)
- [ ] Weaviate-Schema `TradeCase` anlegen + erste Einbindung
- [ ] Simple Fiona-UI: Live-Signale + Risk-Status anzeigen

---

## Definition of Done (für dieses Big Picture Issue)

- Grundarchitektur steht (Module/Services/Dateistruktur)
- Broker Service kann Daten holen (mind. Preis + Account)
- Phase Engine läuft und liefert die korrekte Phase (Asia/London/US/EIA/Freitag)
- Strategy Engine kann mindestens:
  - einfache Breakout-SetupCandidates erzeugen
  - EIA-Zeitfenster erkennen
- KiGate-Anbindung zu:
  - lokalem LLM für Bewertung/Begründung
  - GPT-Reflexion (optional zunächst stub/mock)
- Risk Engine V1 entscheidet `can_trade_now` und per-Trade `approved/rejected`
- Shadow-Trades werden in einer minimalen Form angelegt
- `TradeCase` wird in Weaviate (oder zunächst in einer DB) persistiert
- Ein einfaches UI zeigt:
  - aktuelle Phase
  - mindestens 1–2 Beispiel-Setups + deren KI-Begründung
  - Risk-Status („Handel erlaubt / gesperrt“)

Feintuning, weitere Strategiemodule, Performance-Optimierungen und erweiterte UI/Reports werden in Folge-Issues umgesetzt.
