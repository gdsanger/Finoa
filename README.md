# 🌿 Finoa — Klare Finanzen. Klare Zukunft.

**Finoa** ist eine moderne, minimalistische Finanzverwaltungs-App auf Basis von  
**Django**, **HTMX**, **Bootstrap** und **SQLite**.  
Sie zeigt nicht nur deinen aktuellen finanziellen Stand, sondern auch die Entwicklung der nächsten Monate.

Der Fokus liegt auf:
- Übersicht statt Chaos  
- Forecast statt Bauchgefühl  
- Einfachheit statt unnötiger Komplexität  

---

## 🎨 Brand Identity — Farben & Stil

Finoa verwendet ein ruhiges, modernes Farbkonzept, das Klarheit vermittelt:

| Name     | Hex       | Verwendung |
|----------|-----------|------------|
| **Finoa Green** | `#39A77B` | Akzente, positive Werte, Buttons |
| **Finoa Blue**  | `#3A6EA5` | Diagramme, Header, Navigation |
| **Finoa Grey**  | `#E9ECEF` | Hintergrundbereiche, Karten |
| **Dark Slate**  | `#2E3440` | Text & Dark Mode |
| **Soft White**  | `#F7F9FA` | Light UI Background |

Visuell ist Finoa:
- minimalistisch  
- professionell  
- leicht blau-grün akzentuiert  
- hell mit ruhiger Typografie  

---

## ✨ Features (MVP)

### 🔹 Kontenverwaltung
- Girokonten, Kreditkarten, Trading-Konten, Darlehen, Verbindlichkeiten, Forderungen
- Startsaldo, aktueller Ist-Saldo, Forecast-Saldo

### 🔹 Buchungen
- Ein- und Ausgaben
- Status: `POSTED`, `PLANNED`, `CANCELLED`
- Kategorien für spätere Auswertungen
- Umbuchungen zwischen Konten (automatisch als zwei gekoppelte Buchungen)

### 🔹 Wiederkehrende Buchungen (Grundmodell)
- monatliche Serien (Miete, Gehalt, Versicherungen etc.)
- virtuelle Buchungen für Forecast & Monatsansicht

### 🔹 Forecast
- Kombiniert:
  - echte Buchungen  
  - geplante Buchungen  
  - virtuelle Serienbuchungen  
- 6-Monats- oder Jahresvorschau
- Timeline-Charts (Chart.js)

### 🔹 Monatsansicht (mit HTMX)
- Buchungen pro Monat/Konto
- Inline-Formulare (Anlegen/Bearbeiten/Löschen) ohne Seitenreload
- laufender Monatssaldo

### 🔹 Dashboard
- Gesamtliquidität
- Salden aller Konten
- Erste Forecast-Grafik

---

## 🔮 Geplante Features

### KI-Modul (optional, Phase 2)
- automatische Kategorisierung von Buchungen  
- Vorschläge für wiederkehrende Buchungen  
- Forecast-Analyse in natürlicher Sprache  
- „Was wäre wenn“-Simulationen  

Weitere Erweiterungen:
- CSV/MT940-Import
- Kategorien-Analyse
- PDF-/Excel-Export
- Multi-User-Modus

---

## 🧱 Tech-Stack

| Bereich     | Technologie |
|-------------|-------------|
| Backend     | Django (Python) |
| Frontend    | HTMX + Bootstrap |
| Datenbank   | SQLite |
| Charts      | Chart.js |
| Architektur | Service-basiert (Finance Engine + Recurrence Engine) |

---

## 📂 Projektstruktur (geplant)

```
finoa/
├── core/
│   ├── models/        # Account, Category, Booking, RecurringBooking
│   ├── services/      # Finance-Engine & Forecast
│   ├── views/         # Dashboard, Accounts, Monatsansicht
│   ├── templates/     # Django + HTMX Templates
│   └── static/        # CSS (mit Finoa-Farben), JS, Charts
├── finao/             # Django-Projektbasis
└── README.md
```

---

## 🚀 Installation

### Voraussetzungen
- Python 3.11+
- pip
- sqlite3 (vorinstalliert)

### 1. Repository klonen
```bash
git clone https://github.com/gdsanger/Finoa.git
cd Finoa
```

### 2. Virtualenv erstellen und aktivieren
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

### 3. Dependencies installieren
```bash
pip install -r requirements.txt
```

### 4. Datenbank vorbereiten
```bash
python manage.py migrate
```

### 5. Admin-Benutzer erstellen
```bash
python manage.py createsuperuser
```

Folgen Sie den Anweisungen und erstellen Sie einen Admin-Account.

### 6. Starten
```bash
python manage.py runserver
```

Die App läuft unter:  
👉 **http://127.0.0.1:8000/**

Admin-Interface:  
👉 **http://127.0.0.1:8000/admin/**

---

## 🎬 Erste Schritte

Nach der Installation:

1. **Konto anlegen**: Gehen Sie zum Admin-Interface und erstellen Sie Ihr erstes Konto (z.B. Girokonto)
2. **Kategorien erstellen**: Legen Sie Kategorien an (Gehalt, Miete, Lebensmittel, etc.)
3. **Buchungen erfassen**: Erfassen Sie Ihre Transaktionen
4. **Wiederkehrende Buchungen**: Legen Sie monatliche Serien für regelmäßige Ein-/Ausgaben an
5. **Dashboard nutzen**: Betrachten Sie Ihre Finanzen und Forecasts im Dashboard

---

## 🧪 Tests ausführen

```bash
python manage.py test
```

---

## 🧪 Entwicklungsleitlinien

- Issues → Branches → PR → Merge
- Code nach PEP8
- Views klar trennen in:
  - reguläre Django Views
  - HTMX-Endpoints
- alle Finanzlogik in Services, **keine Berechnungen in Templates**

---

## 📜 Lizenz

MIT License

---

## 🎯 Vision

Finoa soll kein überladenes Budgetmonster sein, sondern ein  
**sauberes, zuverlässiges, vorausschauendes Finanzwerkzeug**, das:

✔ Klarheit schafft  
✔ Buchungen einfach macht  
✔ zukünftige Finanzentwicklung sichtbar macht  
