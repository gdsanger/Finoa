# Document Intake - AI-Powered Receipt/Invoice Processing

## Overview

The Document Intake feature allows Finoa to automatically extract booking information from uploaded receipts and invoices using KIGate AI agents. Text is extracted from images using OpenAI's Vision API and from PDFs using PyMuPDF, then analyzed by the specialized German invoice metadata extraction agent. This streamlines the process of recording transactions by reducing manual data entry.

## Features

- Upload documents (PDF, JPG, JPEG, PNG, GIF, BMP, WEBP)
- Automatic extraction of:
  - Payee/merchant name
  - Amount and currency
  - Date
  - Category
  - Account
  - Description
  - Whether it's a recurring payment
- Review and edit AI suggestions before booking
- Create bookings directly from reviewed documents
- Optional creation of recurring bookings

## Setup

### 1. Configure KIGate API

Before using the document intake feature, you need to configure your KIGate API access:

1. Go to the Django Admin interface (`/admin/`)
2. Navigate to **Core** > **KIGate Configurations**
3. Click **Add KIGate Configuration**
4. Fill in the fields:
   - **Name**: A descriptive name (e.g., "Production KIGate")
   - **Base URL**: Your KIGate API base URL
   - **API Key**: Your KIGate API key (format: `client_id:client_secret`)
   - **Default Agent Name**: `invoice-metadata-extractor-de`
   - **Default Provider**: `openai` (or as configured)
   - **Default Model**: `gpt-4` (or as configured)
   - **Default User ID**: Your user/organization identifier
   - **Max Tokens**: `2000` (default)
   - **Timeout Seconds**: `30` (default)
   - **Is Active**: ✓ Check this box
5. Click **Save**

### 2. Configure OpenAI API (for image text extraction)

For processing image files, configure OpenAI API:

1. Go to the Django Admin interface (`/admin/`)
2. Navigate to **Core** > **OpenAI Configurations**
3. Click **Add OpenAI Configuration**
4. Fill in the fields:
   - **Name**: A descriptive name (e.g., "Production OpenAI")
   - **API Key**: Your OpenAI API key
   - **Base URL**: `https://api.openai.com/v1` (default)
   - **Default Model**: `gpt-4` (for text)
   - **Default Vision Model**: `gpt-4o` (for image text extraction)
   - **Is Active**: ✓ Check this box
5. Click **Save**

### 3. Create Master Data

For the AI to map extracted information correctly, create the following master data:

- **Accounts**: Create your financial accounts (checking, credit card, etc.)
- **Payees**: Create common payees/merchants
- **Categories**: Create expense/income categories

The AI will try to match extracted information to existing records using fuzzy matching.

## Usage

### 1. Upload Documents

1. Navigate to **Dokumente** in the main menu
2. Click **Choose File** and select a receipt or invoice
3. Click **Hochladen** to upload
4. The document will be saved with status "UPLOADED"

### 2. Process Documents

Run the management command to process uploaded documents:

```bash
python manage.py process_document_intake
```

Options:
- `--limit N`: Process only N documents (default: 10)
- `--document-id ID`: Process a specific document by ID

The command will:
1. Find documents with status "UPLOADED"
2. Send them to OpenAI Vision API
3. Extract booking information
4. Try to map to existing accounts, payees, and categories
5. Set status to "REVIEW_PENDING"

### 3. Review and Book

1. Navigate to **Dokumente** > **Prüfen** (or the yellow "Zur Prüfung" card)
2. You'll see all documents awaiting review
3. Click **Prüfen & Verbuchen** on a document
4. Review the AI suggestions:
   - Account
   - Amount
   - Date
   - Payee
   - Category
   - Description
5. Edit any fields as needed
6. If the AI detected a recurring payment, you can check "Als wiederkehrende Buchung anlegen"
7. Click **Buchung erstellen**

The booking will be created and linked to the document.

## AI Processing Details

### Processing Pipeline

1. **Text Extraction**:
   - **PDFs**: Text is extracted using PyMuPDF (fitz)
   - **Images**: Text is extracted using OpenAI Vision API

2. **Metadata Extraction**:
   - Extracted text is sent to KIGate agent `invoice-metadata-extractor-de`
   - Agent analyzes the text and returns structured metadata in German format:
     - **Belegnummer**: Document/invoice number
     - **Absender**: Sender/merchant name
     - **Betrag**: Amount with currency (e.g., "27,03 €")
     - **Fällig**: Due date in German format (e.g., "13. Dezember 2025")
     - **Info**: Additional information/description

3. **Data Conversion**:
   - German fields are converted to internal format
   - Amount is parsed from German format (comma as decimal separator)
   - Date is parsed from German natural language format
   - Description is created by combining Belegnummer and Info

### Extracted Information

The system extracts and maps the following information:

- **payee_name**: Merchant or payment recipient (from "Absender")
- **amount**: Transaction amount (parsed from "Betrag", e.g., "27,03 €" → 27.03)
- **currency**: Currency code (EUR, USD, etc., extracted from "Betrag")
- **date**: Transaction date (parsed from "Fällig", e.g., "13. Dezember 2025" → "2025-12-13")
- **description**: Combined from "Belegnummer" and "Info" fields
- **confidence**: AI's confidence level (0.8 default for KIGate)
- **extracted_text**: Full text extracted from the document

### Mapping Strategy

The system uses the following strategy to map extracted data:

1. **Exact Match**: Try to find an exact match (case-insensitive)
2. **Partial Match**: If no exact match, try partial matching
3. **No Match**: Leave as null, user can select manually during review

### Error Handling

If processing fails:
- Document status is set to "ERROR"
- Error message is stored in `error_message` field
- Check the error message in the admin interface
- Common errors:
  - No active KIGate configuration
  - No active OpenAI configuration (for image processing)
  - Invalid API key
  - Network issues
  - Unsupported file format
  - KIGate agent not found or misconfigured
  - Failed to parse KIGate response

## Status Flow

Documents progress through the following statuses:

1. **UPLOADED**: Initial upload, awaiting processing
2. **AI_PROCESSING**: Currently being analyzed by AI
3. **AI_DONE**: Analysis complete (intermediate state)
4. **REVIEW_PENDING**: Ready for user review
5. **BOOKED**: Booking created from document
6. **ERROR**: Processing failed

## Tips for Best Results

### Document Quality

- Use clear, high-resolution images
- Ensure text is readable
- Avoid blurry or dark photos
- PDFs work best for scanned documents

### Improving Accuracy

- Create payees before uploading documents
- Use consistent category names
- Review and correct AI suggestions
- The AI learns from the structure of your existing data

### Recurring Payments

The AI will suggest `is_recurring: true` when it detects keywords like:
- "monatlich" (monthly)
- "jährlich" (yearly)
- "Abo" (subscription)
- "Mitgliedschaft" (membership)

## Troubleshooting

### Documents Not Processing

1. Check that KIGate configuration is active
2. Check that OpenAI configuration is active (for image processing)
3. Verify API keys are correct
4. Check error messages in admin interface
5. Ensure file formats are supported
6. Verify KIGate agent "invoice-metadata-extractor-de" exists

### Low Accuracy

1. Improve image quality
2. Ensure master data (accounts, payees, categories) exists
3. Check confidence score - low scores indicate uncertain extraction
4. Review extracted_text to see what the AI "saw"
5. Verify KIGate agent is properly configured for German invoices

### Performance

- Processing time depends on:
  - Document size and complexity
  - Text extraction time (faster for PDFs, slower for images)
  - KIGate API response time
  - Network speed
- Typical processing: 5-15 seconds per document
- Use `--limit` flag to process in batches

## Cost Considerations

- Each document processed consumes API credits from:
  - KIGate API (for metadata extraction)
  - OpenAI API (for image text extraction only)
- Image processing is more expensive due to Vision API usage
- PDF processing is cheaper (only text extraction, then KIGate)
- Monitor your KIGate and OpenAI usage dashboards
- Consider batch processing during off-peak hours

## Future Enhancements

Potential future improvements:
- Automatic processing on upload (webhook/celery task)
- Batch upload and processing
- Historical learning from confirmed bookings
- Multi-language support
- Integration with email (forward receipts)
- Mobile app upload
