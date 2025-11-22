# KIGate API Dokumentation

## Übersicht

KIGate ist ein zentralisiertes, agenten-basiertes API Gateway für AI-Services. Diese API ermöglicht es externen Software-Projekten, verschiedene AI-Provider über eine einheitliche Schnittstelle zu nutzen und dabei vordefinierte Agenten mit spezifischen Rollen und Aufgaben zu verwenden.

## 🔒 Zugriff und Netzwerk

**Wichtiger Hinweis**: Diese API ist **nicht öffentlich im Internet verfügbar**. Der Zugriff ist nur möglich über:
- Das **Sternnetzerwerk** (interne Netzwerkverbindung)
- **VPN-Verbindung** zum Unternehmensnetzwerk

**Zugangsdaten** und weitere technische Details erhalten Sie bei:
**Christian Angermeier**  
📧 christian.angermeier@isartec.de  
*Ansprechpartner und Maintainer*

## 🚀 Hauptendpoint: `/agent/execute`

### Beschreibung

Der `/agent/execute` Endpunkt ist der Kernbestandteil der KIGate API. Er ermöglicht es, einen vordefinierten Agenten mit einer Benutzernachricht auszuführen und eine AI-generierte Antwort zu erhalten.

### HTTP Method
```
POST /agent/execute
```

### Authentifizierung

Die API unterstützt zwei Authentifizierungsmethoden:

#### 1. Bearer Token (Empfohlen)
```bash
curl -X POST "https://kigate.isarlabs.de/agent/execute" \
     -H "Authorization: Bearer {client_id}:{client_secret}" \
     -H "Content-Type: application/json" \
     -d @request.json
```

#### 2. API Key Parameter
```bash
curl -X POST "https://kigate.isarlabs.de/agent/execute?api_key={client_id}:{client_secret}" \
     -H "Content-Type: application/json" \
     -d @request.json
```

### Request Format

```json
{
    "agent_name": "string",
    "provider": "string", 
    "model": "string",
    "message": "string",
    "user_id": "string",
    "parameters": {
        "key": "value"
    }
}
```

#### Request Parameter

| Parameter | Typ | Pflicht | Beschreibung |
|-----------|-----|---------|--------------|
| `agent_name` | string | ✅ | Name des zu verwendenden Agenten (1-100 Zeichen) |
| `provider` | string | ✅ | AI-Provider Name (1-50 Zeichen) |
| `model` | string | ✅ | Spezifisches AI-Modell (1-100 Zeichen) |
| `message` | string | ✅ | Benutzernachricht für den Agenten |
| `user_id` | string | ✅ | Eindeutige Benutzer-ID (1-36 Zeichen) |
| `parameters` | object | ❌ | Optionale Parameter für den Agenten als Schlüssel-Wert-Paare |

### Response Format

```json
{
    "job_id": "string",
    "agent": "string",
    "provider": "string", 
    "model": "string",
    "status": "string",
    "result": "string"
}
```

#### Response Parameter

| Parameter | Typ | Beschreibung |
|-----------|-----|-------------|
| `job_id` | string | Eindeutige ID für diesen Ausführungsauftrag |
| `agent` | string | Name des verwendeten Agenten |
| `provider` | string | Verwendeter AI-Provider |
| `model` | string | Verwendetes AI-Modell |
| `status` | string | Status der Ausführung (z.B. "completed", "processing", "failed") |
| `result` | string | Generierte Antwort vom AI-Provider |

### Beispiel Request

```json
{
    "agent_name": "translation-agent",
    "provider": "openai",
    "model": "gpt-4",
    "message": "Hello, how are you today?",
    "user_id": "user-123-456",
    "parameters": {
        "language": "German"
    }
}
```

### Beispiel Response

```json
{
    "job_id": "job-789-abc-def",
    "agent": "translation-agent",
    "provider": "openai",
    "model": "gpt-4", 
    "status": "completed",
    "result": "Hallo, wie geht es dir heute?"
}
```

### Beispiel ohne Parameter

```json
{
    "agent_name": "translation-agent",
    "provider": "openai",
    "model": "gpt-4",
    "message": "Translate this text to German: Hello, how are you today?",
    "user_id": "user-123-456"
}
```
**Hinweis:** Parameter sind optional. Wenn keine Parameter angegeben werden, verwendet der Agent seine Standardkonfiguration.

## 🤖 Provider System

### Verfügbare Provider

KIGate unterstützt derzeit folgende AI-Provider:

#### 1. OpenAI (`openai`)
Die OpenAI-Integration bietet Zugang zu den GPT-Modellen.

**Top 5 Modelle:**
1. `gpt-4` - Neuestes und leistungsstärkstes Modell
2. `gpt-4-turbo` - Optimiert für Geschwindigkeit und Effizienz  
3. `gpt-3.5-turbo` - Schnell und kosteneffizient
4. `gpt-4-32k` - Erweiterte Kontextlänge
5. `gpt-3.5-turbo-16k` - Erweiterte Kontextlänge für 3.5

#### 2. Claude (`claude`)
Anthropics Claude-Familie für sichere und hilfreiche AI-Interaktionen.

**Top 5 Modelle:**
1. `claude-3-sonnet-20240229` - Ausgewogen zwischen Geschwindigkeit und Qualität
2. `claude-3-opus-20240229` - Höchste Qualität für komplexe Aufgaben
3. `claude-3-haiku-20240307` - Schnell und effizient
4. `claude-2.1` - Vorherige Generation, bewährt
5. `claude-2.0` - Stabile Basisversion

#### 3. Google Gemini (`gemini`)
Googles fortschrittliche Multimodal-AI-Modelle.

**Top 5 Modelle:**
1. `gemini-pro` - Standard-Modell für die meisten Anwendungen
2. `gemini-pro-vision` - Multimodal mit Bilderkennung
3. `gemini-1.5-pro` - Erweiterte Version mit verbesserter Leistung
4. `gemini-1.0-pro` - Stabile Basisversion
5. `gemini-nano` - Kompakte Version für einfache Aufgaben

#### 4. ISARtec/Ollama (`isartec`)
⚠️ **Hinweis**: Diese Integration ist derzeit in Entwicklung und noch nicht vollständig implementiert.

**Geplante Modelle:**
1. `llama-2-7b` - Meta's Llama 2 Basismodell
2. `llama-2-13b` - Größeres Llama 2 Modell
3. `codellama` - Speziell für Code-Generation
4. `mistral-7b` - Mistral AI Modell
5. `neural-chat` - Konversationsmodell

## 📋 Agent-Konzept

### Was sind Agenten?

Agenten sind vordefinierte AI-Konfigurationen mit spezifischen Rollen, Aufgaben und Parametern. Sie werden als YAML-Dateien gespeichert und kombinieren:

- **Rolle**: Grundlegende Identität des Agenten
- **Aufgabe**: Spezifische Anweisungen und Verhalten
- **Provider**: Welcher AI-Service verwendet wird
- **Modell**: Welches spezifische Modell verwendet wird
- **Parameter**: Zusätzliche Konfigurationen

### 🔧 Parameter-Verwendung

Parameter ermöglichen es, das Verhalten von Agenten zur Laufzeit anzupassen, ohne die Agent-Konfiguration zu ändern.

#### Funktionsweise

1. **Parameter-Definition**: Agenten definieren in ihrer YAML-Datei verfügbare Parameter
2. **Parameter-Übermittlung**: Im API-Request werden Parameter als Key-Value-Paare übergeben
3. **Parameter-Integration**: Die API kombiniert die Parameter mit der Agent-Aufgabe
4. **Ausführung**: Der AI-Provider erhält die parametrisierte Aufgabe

#### Parameter-Format im Request

```json
{
    "parameters": {
        "parameter_name": "wert",
        "another_parameter": "anderer_wert"
    }
}
```

#### Beispiel: Translation-Agent mit Language-Parameter

**Agent-Definition (translation-agent.yml):**
```yaml
name: translation-agent
description: An agent that accurately translates text into target languages
role: You are a translation agent.
provider: openai
model: gpt-4
task: |
  Translate a given text into the specified target language.
  - Preserve original meaning, tone, and style
  - Do not add or omit information
  - Maintain formatting and structure
parameters:
  - language:
      description: The language in has to be translated.
      type: string
```

**API Request mit Parameter:**
```json
{
    "agent_name": "translation-agent",
    "provider": "openai",
    "model": "gpt-4",
    "message": "Hello, how are you today?",
    "user_id": "user-123-456",
    "parameters": {
        "language": "French"
    }
}
```

**Verarbeitete Aufgabe (intern):**
```
You are a translation agent.

Translate a given text into the specified target language.
- Preserve original meaning, tone, and style
- Do not add or omit information
- Maintain formatting and structure

Parameters:
language: French

User message: Hello, how are you today?
```

### Agent-Beispiel

```yaml
name: translation-agent
description: An agent that accurately translates text into target languages
role: You are a translation agent.
provider: openai
model: gpt-4
task: |
  Translate a given text into the specified target language.
  - Preserve original meaning, tone, and style
  - Do not add or omit information
  - Maintain formatting and structure
parameters:
  - Inputtext: 
      type: string
      description: The text to be translated
  - Model: 
      type: string
      description: The language model to use
      default: gpt-4
```

### Verwendung von Agenten

1. **Agent-Name**: Muss exakt mit dem Dateinamen (ohne .yml) übereinstimmen
2. **Provider-Matching**: Provider im Request muss mit Agent-Konfiguration übereinstimmen
3. **Model-Matching**: Model im Request muss mit Agent-Konfiguration übereinstimmen
4. **Nachrichtenkombination**: Ihre Nachricht wird mit Rolle und Aufgabe des Agenten kombiniert

## 🔍 Weitere API Endpunkte

### Health Check
```bash
GET /health?api_key={client_id}:{client_secret}
```

### Verfügbare Agenten auflisten
```bash  
GET /api/agents?api_key={client_id}:{client_secret}
```

## ⚠️ Fehlerbehandlung

### Häufige Fehler

#### 404 - Agent nicht gefunden
```json
{
    "detail": "Agent 'non-existent-agent' not found"
}
```

#### 400 - Provider stimmt nicht überein
```json
{
    "detail": "Provider 'claude' does not match agent configuration 'openai'"
}
```

#### 400 - Modell stimmt nicht überein  
```json
{
    "detail": "Model 'gpt-3.5-turbo' does not match agent configuration 'gpt-4'"
}
```

#### 401 - Authentifizierung fehlgeschlagen
```json
{
    "detail": "Invalid API key"
}
```

### HTTP Status Codes

| Code | Bedeutung |
|------|-----------|
| 200 | Erfolgreich ausgeführt |
| 400 | Ungültiger Request (Parameter, Agent-Konfiguration) |
| 401 | Authentifizierung fehlgeschlagen |
| 404 | Agent nicht gefunden |
| 500 | Interner Serverfehler |

## 🛠️ Implementierungsbeispiele

### Python mit requests

```python
import requests
import json

url = "https://kigate.isarlabs.de/agent/execute"
headers = {
    "Authorization": "Bearer your_client_id:your_client_secret",
    "Content-Type": "application/json"
}

# Beispiel mit Parameter
data = {
    "agent_name": "translation-agent",
    "provider": "openai", 
    "model": "gpt-4",
    "message": "Good morning!",
    "user_id": "user-12345",
    "parameters": {
        "language": "German"
    }
}

response = requests.post(url, headers=headers, json=data)
result = response.json()

print(f"Status: {result['status']}")
print(f"Result: {result['result']}")

# Beispiel ohne Parameter
data_no_params = {
    "agent_name": "translation-agent",
    "provider": "openai", 
    "model": "gpt-4",
    "message": "Translate to Spanish: Good morning!",
    "user_id": "user-12345"
}

response2 = requests.post(url, headers=headers, json=data_no_params)
result2 = response2.json()

print(f"Status: {result2['status']}")
print(f"Result: {result2['result']}")
```

### JavaScript/Node.js

```javascript
const axios = require('axios');

const executeAgentWithParameters = async () => {
    try {
        // Beispiel mit Parameter
        const response = await axios.post(
            'https://kigate.isarlabs.de/agent/execute',
            {
                agent_name: 'translation-agent',
                provider: 'openai',
                model: 'gpt-4', 
                message: 'Good morning!',
                user_id: 'user-12345',
                parameters: {
                    language: 'German'
                }
            },
            {
                headers: {
                    'Authorization': 'Bearer your_client_id:your_client_secret',
                    'Content-Type': 'application/json'
                }
            }
        );
        
        console.log('With parameters - Status:', response.data.status);
        console.log('With parameters - Result:', response.data.result);
        
        // Beispiel ohne Parameter
        const response2 = await axios.post(
            'https://kigate.isarlabs.de/agent/execute',
            {
                agent_name: 'translation-agent',
                provider: 'openai',
                model: 'gpt-4', 
                message: 'Translate to Spanish: Good morning!',
                user_id: 'user-12345'
            },
            {
                headers: {
                    'Authorization': 'Bearer your_client_id:your_client_secret',
                    'Content-Type': 'application/json'
                }
            }
        );
        
        console.log('Without parameters - Status:', response2.data.status);
        console.log('Without parameters - Result:', response2.data.result);
        
    } catch (error) {
        console.error('Error:', error.response?.data || error.message);
    }
};

executeAgentWithParameters();
```

### cURL Beispiele

#### Mit Parameter

```bash
curl -X POST "https://kigate.isarlabs.de/agent/execute" \
     -H "Authorization: Bearer your_client_id:your_client_secret" \
     -H "Content-Type: application/json" \
     -d '{
       "agent_name": "translation-agent",
       "provider": "openai",
       "model": "gpt-4",
       "message": "Good morning!",
       "user_id": "user-12345",
       "parameters": {
         "language": "German"
       }
     }'
```

#### Ohne Parameter

```bash
curl -X POST "https://kigate.isarlabs.de/agent/execute" \
     -H "Authorization: Bearer your_client_id:your_client_secret" \
     -H "Content-Type: application/json" \
     -d '{
       "agent_name": "translation-agent",
       "provider": "openai",
       "model": "gpt-4",
       "message": "Translate to Spanish: Good morning!",
       "user_id": "user-12345"
     }'
```

## 📊 Best Practices

### 1. Agent-Auswahl
- Wählen Sie Agenten basierend auf der spezifischen Aufgabe
- Stellen Sie sicher, dass Provider und Modell verfügbar sind
- Testen Sie verschiedene Agenten für optimale Ergebnisse

### 2. Fehlerbehandlung
- Implementieren Sie Retry-Logic für temporäre Fehler
- Validieren Sie Input-Parameter vor dem Request
- Loggen Sie job_id für Debugging-Zwecke

### 3. Performance
- Verwenden Sie angemessene Modelle für Ihre Anforderungen
- Cachén Sie Ergebnisse wenn möglich
- Implementieren Sie Request-Timeouts

### 4. Sicherheit
- Speichern Sie API-Schlüssel sicher
- Verwenden Sie HTTPS für alle Requests
- Rotieren Sie Zugangsdaten regelmäßig

## 🆘 Support und Kontakt

Bei Fragen, Problemen oder Anfragen zur API-Nutzung wenden Sie sich an:

**Christian Angermeier**  
📧 christian.angermeier@isartec.de  
*Maintainer und Ansprechpartner für KIGate API*

**Verfügbare Unterstützung:**
- API-Zugangsdaten und Autorisierung
- Technische Implementierungshilfe  
- Agent-Konfiguration und -Erstellung
- Troubleshooting und Fehlerdiagnose
- VPN/Netzwerk-Zugang

---

*Diese Dokumentation wird regelmäßig aktualisiert. Version: 1.0 - Oktober 2024*