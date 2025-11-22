# Document Intake - AI-Powered Receipt/Invoice Processing

## Overview

The Document Intake feature allows Finoa to automatically extract booking information from uploaded receipts and invoices using OpenAI's Vision API. This streamlines the process of recording transactions by reducing manual data entry.

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

### 1. Configure OpenAI API

Before using the document intake feature, you need to configure your OpenAI API key:

1. Go to the Django Admin interface (`/admin/`)
2. Navigate to **Core** > **OpenAI Configurations**
3. Click **Add OpenAI Configuration**
4. Fill in the fields:
   - **Name**: A descriptive name (e.g., "Production OpenAI")
   - **API Key**: Your OpenAI API key
   - **Base URL**: `https://api.openai.com/v1` (default)
   - **Default Model**: `gpt-4` (for text)
   - **Default Vision Model**: `gpt-4-vision-preview` (for document analysis)
   - **Is Active**: ✓ Check this box
5. Click **Save**

### 2. Create Master Data

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

### Extracted Information

The AI attempts to extract the following information from documents:

- **payee_name**: Merchant or payment recipient
- **account_name**: Bank account name (if mentioned)
- **category_name**: Expense category
- **amount**: Transaction amount
- **currency**: Currency code (EUR, USD, etc.)
- **date**: Transaction date (YYYY-MM-DD)
- **description**: Brief description
- **is_recurring**: Whether it appears to be a recurring payment
- **confidence**: AI's confidence level (0.0-1.0)
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
  - No active OpenAI configuration
  - Invalid API key
  - Network issues
  - Unsupported file format

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

1. Check that OpenAI configuration is active
2. Verify API key is correct
3. Check error messages in admin interface
4. Ensure file formats are supported

### Low Accuracy

1. Improve image quality
2. Ensure master data (accounts, payees, categories) exists
3. Check confidence score - low scores indicate uncertain extraction
4. Review extracted_text to see what the AI "saw"

### Performance

- Processing time depends on:
  - Document size and complexity
  - OpenAI API response time
  - Network speed
- Typical processing: 5-15 seconds per document
- Use `--limit` flag to process in batches

## Cost Considerations

- Each document processed consumes OpenAI API credits
- Vision API calls are more expensive than text-only calls
- Monitor your OpenAI usage dashboard
- Consider batch processing during off-peak hours

## Future Enhancements

Potential future improvements:
- Automatic processing on upload (webhook/celery task)
- Batch upload and processing
- Historical learning from confirmed bookings
- Multi-language support
- Integration with email (forward receipts)
- Mobile app upload
