# KIGate API - Quick Reference

## 🔗 Base URL
```
https://kigate.isarlabs.de
```

## 🔑 Authentication 
```bash
Authorization: Bearer {client_id}:{client_secret}
```

## 🚀 Execute Agent
```bash
POST /agent/execute
```

**Request:**
```json
{
    "agent_name": "string",
    "provider": "string", 
    "model": "string",
    "message": "string",
    "user_id": "string"
}
```

**Response:**
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

## 🤖 Top Models by Provider

### OpenAI
- `gpt-4` 
- `gpt-4-turbo`
- `gpt-3.5-turbo`

### Claude  
- `claude-3-sonnet-20240229`
- `claude-3-opus-20240229`
- `claude-3-haiku-20240307`

### Gemini
- `gemini-pro`
- `gemini-pro-vision` 
- `gemini-1.5-pro`

## 📞 Support
**Christian Angermeier**  
christian.angermeier@isartec.de

⚠️ **Network**: Sternnetzerwerk/VPN only