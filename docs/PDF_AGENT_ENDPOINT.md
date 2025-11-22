# PDF Agent Execution Endpoint

## Overview

The PDF Agent Execution Endpoint allows you to execute agents with PDF files as input instead of text messages. The endpoint uses a JSON structure similar to `/agent/execute` but accepts a PDF file instead of a message field. The endpoint automatically extracts text from the PDF, splits it into manageable chunks if needed, processes each chunk through the specified agent, and merges the results into a coherent final response.

## Endpoint

```
POST /agent/execute-pdf
```

## Authentication

Requires Bearer token authentication (same as other agent endpoints).

## Request Format

The request uses `multipart/form-data` format with JSON structure similar to `/agent/execute`:

- `request` (string, required): JSON string containing the agent execution parameters  
- `pdf_file` (file, required): PDF file to process (must have .pdf extension)

### JSON Structure in `request` field

```json
{
  "agent_name": "string",
  "provider": "string", 
  "model": "string",
  "user_id": "string",
  "parameters": {
    "additionalProp1": {}
  },
  "chunk_size": 4000
}
```

### Field Descriptions

- `agent_name` (string, required): Name of the agent to execute
- `provider` (string, required): AI provider (must match agent configuration)
- `model` (string, required): AI model (must match agent configuration)  
- `user_id` (string, required): User ID for tracking
- `parameters` (object, optional): Optional key-value parameters for the agent (same as `/agent/execute`)
- `chunk_size` (integer, optional): Maximum size of text chunks (default: 4000)

## Response

```json
{
  "job_id": "string",
  "agent": "string", 
  "provider": "string",
  "model": "string",
  "status": "string",
  "result": "string",
  "chunks_processed": "integer",
  "pdf_filename": "string"
}
```

## How It Works

1. **File Validation**: Validates that the uploaded file has a `.pdf` extension
2. **Agent Validation**: Verifies the agent exists and provider/model match the agent configuration
3. **Text Extraction**: Extracts text content from all pages of the PDF using pypdf library
4. **Text Chunking**: If the extracted text exceeds the chunk size, splits it into smaller pieces with intelligent boundary detection (sentence/paragraph breaks)
5. **Processing**: Each chunk is processed independently through the specified agent
6. **Result Merging**: 
   - For single chunks: Returns the result directly
   - For multiple chunks: Uses AI to intelligently merge results into a coherent final report
7. **Job Tracking**: Creates database jobs for each chunk to track processing status

## Features

### Intelligent Text Chunking
- Respects sentence and paragraph boundaries when splitting text
- Configurable chunk size to stay within token limits
- Includes overlap between chunks to maintain context

### Multi-Page Support
- Extracts text from all pages in the PDF
- Preserves page structure with page markers

### Error Handling
- Graceful handling of PDF processing errors
- Partial success support (some chunks succeed, others fail)
- Detailed error messages for debugging

### Result Merging
- Simple concatenation for basic cases
- AI-powered intelligent merging for complex multi-chunk results
- Structured output format with section-based organization

## Status Values

- `completed`: All chunks processed successfully
- `failed`: All chunks failed to process
- `partially_completed`: Some chunks succeeded, others failed

## Example Usage

### Using cURL

```bash
# Prepare the JSON request data
JSON_DATA='{
  "agent_name": "documentation-example-agent",
  "provider": "openai", 
  "model": "gpt-3.5-turbo",
  "user_id": "user-123",
  "parameters": {
    "Anweisung": "Erstelle eine Zusammenfassung"
  },
  "chunk_size": 4000
}'

# Send the request  
curl -X POST "http://localhost:8000/agent/execute-pdf" \
  -H "Authorization: Bearer your-token-here" \
  -F "request=${JSON_DATA}" \
  -F "pdf_file=@/path/to/document.pdf"
```

### Using Python with requests

```python
import requests
import json

# Prepare the JSON data
request_data = {
    "agent_name": "documentation-example-agent",
    "provider": "openai",
    "model": "gpt-3.5-turbo", 
    "user_id": "user-123",
    "parameters": {
        "Anweisung": "Erstelle eine Zusammenfassung"
    },
    "chunk_size": 4000
}

# Prepare the files for upload
files = {
    'request': (None, json.dumps(request_data)),
    'pdf_file': ('document.pdf', open('/path/to/document.pdf', 'rb'), 'application/pdf')
}

# Send the request
response = requests.post(
    'http://localhost:8000/agent/execute-pdf',
    headers={'Authorization': 'Bearer your-token-here'},
    files=files
)

print(response.json())
```

## Error Responses

### 400 Bad Request
- Invalid file extension (not .pdf)
- Agent provider/model mismatch
- PDF processing error

### 404 Not Found
- Agent not found

### 500 Internal Server Error
- Unexpected processing error

## Limitations

- Only PDF files are supported (must have .pdf extension)
- Text-based PDFs only (image/scanned PDFs may not extract properly)
- Processing time increases with document size and number of chunks
- Token limits depend on the configured AI provider and model

## Dependencies

- `pypdf`: For PDF text extraction
- `fastapi`: Web framework
- Existing agent and AI service infrastructure