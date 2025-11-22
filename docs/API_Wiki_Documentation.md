# KIGate API - Entwickler Wiki

## Überblick

KIGate ist ein zentralisiertes API Gateway für AI-Services. Diese Dokumentation erklärt, wie Sie die API in Ihren Softwareprojekten nutzen können.

## 🔐 Zugriff & Authentifizierung

### Netzwerkzugriff
⚠️ **Wichtig**: API nur über **Sternnetzerwerk** oder **VPN** erreichbar, nicht öffentlich im Internet.

### Kontakt für Zugangsdaten
**Christian Angermeier** (christian.angermeier@isartec.de)  
*Ansprechpartner und Maintainer*

### Authentifizierung
```bash
# Bearer Token (empfohlen)
Authorization: Bearer {client_id}:{client_secret}

# oder als Query Parameter  
?api_key={client_id}:{client_secret}
```

## 🚀 Haupt-Endpoint: `/agent/execute`

### Request
```http
POST /agent/execute
Content-Type: application/json

{
    "agent_name": "translation-agent",
    "provider": "openai", 
    "model": "gpt-4",
    "message": "Translate to German: Hello World",
    "user_id": "user-123"
}
```

### Response
```json
{
    "job_id": "job-abc-123", 
    "agent": "translation-agent",
    "provider": "openai",
    "model": "gpt-4",
    "status": "completed",
    "result": "Hallo Welt"
}
```

## 🤖 Provider & Modelle

### OpenAI (`openai`)
- `gpt-4` - Bestes Modell für komplexe Aufgaben
- `gpt-4-turbo` - Schneller und effizienter  
- `gpt-3.5-turbo` - Kosteneffizient für einfache Tasks
- `gpt-4-32k` - Erweiterte Kontextlänge
- `gpt-3.5-turbo-16k` - Mehr Kontext für 3.5

### Claude (`claude`)  
- `claude-3-sonnet-20240229` - Ausgewogen
- `claude-3-opus-20240229` - Höchste Qualität
- `claude-3-haiku-20240307` - Schnell
- `claude-2.1` - Bewährt und stabil
- `claude-2.0` - Basis-Version

### Gemini (`gemini`)
- `gemini-pro` - Standard für die meisten Cases
- `gemini-pro-vision` - Mit Bilderkennung  
- `gemini-1.5-pro` - Erweiterte Version
- `gemini-1.0-pro` - Stabile Basis
- `gemini-nano` - Kompakt für einfache Tasks

### ISARtec/Ollama (`isartec`) 
🚧 **In Entwicklung** - Lokale Modelle geplant:
- `llama-2-7b`, `llama-2-13b`
- `codellama`, `mistral-7b`, `neural-chat`

## 📋 Agent-System

### Konzept
Agenten sind vordefinierte AI-Konfigurationen mit:
- **Rolle**: Grundlegende Identität  
- **Aufgabe**: Spezifische Anweisungen
- **Provider/Modell**: Technische Konfiguration

### Wichtige Regeln
✅ `agent_name` muss exakt mit YAML-Datei übereinstimmen  
✅ `provider` und `model` müssen mit Agent-Konfiguration matchen  
✅ Ihre Nachricht wird mit Agent-Rolle/Aufgabe kombiniert  

### Verfügbare Agenten
- `translation-agent` - Übersetzungen (OpenAI/GPT-4)
- `exam-content-agent` - Essay-Bewertung (OpenAI/GPT-4)  
- `text-optimization-agent` - Text-Verbesserung
- Weitere über `/api/agents` abrufbar

## 💻 Code-Beispiele

### Python
```python
import requests

response = requests.post(
    'https://kigate.isarlabs.de/agent/execute',
    headers={'Authorization': 'Bearer client_id:client_secret'},
    json={
        'agent_name': 'translation-agent',
        'provider': 'openai',
        'model': 'gpt-4', 
        'message': 'Translate: Hello World',
        'user_id': 'user-123'
    }
)
print(response.json()['result'])
```

### JavaScript
```javascript
const response = await fetch('https://kigate.isarlabs.de/agent/execute', {
    method: 'POST',
    headers: {
        'Authorization': 'Bearer client_id:client_secret',
        'Content-Type': 'application/json'
    },
    body: JSON.stringify({
        agent_name: 'translation-agent',
        provider: 'openai',
        model: 'gpt-4',
        message: 'Translate: Hello World', 
        user_id: 'user-123'
    })
});
const result = await response.json();
console.log(result.result);
```

## ❌ Häufige Fehler

| Error | Ursache | Lösung |
|-------|---------|---------|
| `404 Agent not found` | Falscher agent_name | Prüfen Sie verfügbare Agenten |
| `400 Provider mismatch` | Provider ≠ Agent-Config | Verwenden Sie korrekten Provider |  
| `400 Model mismatch` | Model ≠ Agent-Config | Verwenden Sie korrektes Modell |
| `401 Invalid API key` | Falsche Credentials | Neue Zugangsdaten anfordern |

## 🔧 Weitere Endpoints

```bash
# Health Check
GET /health?api_key=client_id:client_secret

# Verfügbare Agenten
GET /api/agents?api_key=client_id:client_secret

# OpenAPI Dokumentation  
GET /docs
```

## 📞 Support

**Christian Angermeier**  
📧 christian.angermeier@isartec.de

Unterstützung bei:
- Zugangsdaten & API Keys
- VPN-Setup & Netzwerkzugang  
- Implementierungshilfe
- Agent-Konfiguration
- Troubleshooting

---
*KIGate API Wiki - Maintainer: Christian Angermeier*