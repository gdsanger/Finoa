"""
Document processor for AI-powered analysis of receipts and invoices.
Uses OpenAI Vision API for images and text extraction for PDFs.
"""
import base64
import json
from typing import Dict, Any, Optional
from decimal import Decimal, InvalidOperation
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF

from django.core.files.uploadedfile import UploadedFile

from .openai_client import call_openai_chat, get_active_openai_config


def encode_file_to_base64(file_path: str) -> str:
    """
    Encode a file to base64 for OpenAI Vision API.
    
    Args:
        file_path: Path to the file to encode.
        
    Returns:
        str: Base64 encoded file content.
    """
    with open(file_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


def get_mime_type(filename: str) -> str:
    """
    Determine MIME type from filename extension.
    
    Args:
        filename: Name of the file.
        
    Returns:
        str: MIME type.
    """
    ext = Path(filename).suffix.lower()
    mime_types = {
        '.pdf': 'application/pdf',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.bmp': 'image/bmp',
        '.webp': 'image/webp',
    }
    return mime_types.get(ext, 'application/octet-stream')


def is_image_mime_type(mime_type: str) -> bool:
    """
    Check if MIME type is an image.
    
    Args:
        mime_type: MIME type string.
        
    Returns:
        bool: True if the MIME type is an image, False otherwise.
    """
    return mime_type.startswith('image/')


def extract_text_from_pdf(file_path: str) -> str:
    """
    Extract text from a PDF file using PyMuPDF.
    
    Args:
        file_path: Path to the PDF file.
        
    Returns:
        str: Extracted text from the PDF.
        
    Raises:
        FileNotFoundError: If the PDF file doesn't exist.
        RuntimeError: If PDF extraction fails.
    """
    try:
        doc = fitz.open(file_path)
        text_parts = []
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            text_parts.append(page.get_text())
        
        doc.close()
        
        return '\n'.join(text_parts)
    except FileNotFoundError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to extract text from PDF: {str(e)}") from e


def process_document_with_openai(file_path: str, mime_type: str) -> Dict[str, Any]:
    """
    Process a document using OpenAI to extract booking information.
    For images: uses Vision API with base64-encoded image.
    For PDFs: extracts text with PyMuPDF and processes with regular chat API.
    
    Args:
        file_path: Path to the document file.
        mime_type: MIME type of the document.
        
    Returns:
        dict: Extracted information or error details.
    """
    try:
        config = get_active_openai_config()
        
        # Build the base prompt for extraction
        base_prompt = """Analysiere dieses Dokument (Beleg/Rechnung) und extrahiere folgende Informationen im JSON-Format:

{
  "payee_name": "Name des Zahlungsempfängers/Händlers",
  "account_name": "Kontoname (z.B. 'Girokonto', 'Kreditkarte'). Wenn nicht erkennbar, null.",
  "category_name": "Kategoriename für die Buchung (z.B. 'Lebensmittel', 'Miete', 'Benzin', 'Versicherung')",
  "amount": "Betrag als Zahl (z.B. 42.50)",
  "currency": "Währung (z.B. 'EUR', 'USD')",
  "date": "Datum im Format YYYY-MM-DD",
  "description": "Kurze Beschreibung der Transaktion",
  "is_recurring": true/false (ob es sich um eine wiederkehrende Zahlung handelt),
  "confidence": 0.0-1.0 (Gesamtvertrauen in die Extraktion),
  "extracted_text": "Vollständiger extrahierter Text aus dem Dokument"
}

Wichtig:
- Gib nur valides JSON zurück, ohne zusätzliche Erklärungen
- Wenn ein Feld nicht erkennbar ist, verwende null
- Der Betrag sollte positiv sein für Ausgaben
- Das Datum sollte das Belegdatum sein, nicht das Bezahldatum
- is_recurring: true nur bei klar erkennbaren Abos/Mitgliedschaften (z.B. "monatlich", "jährlich")
- confidence: Wie sicher bist du bei der Extraktion? (0.0 = sehr unsicher, 1.0 = sehr sicher)
- extracted_text: Alle lesbare Texte aus dem Dokument"""
        
        # Determine processing method based on MIME type
        if is_image_mime_type(mime_type):
            # Process image with Vision API
            base64_content = encode_file_to_base64(file_path)
            
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": base_prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64_content}"
                            }
                        }
                    ]
                }
            ]
            
            # Call OpenAI with vision model
            response = call_openai_chat(
                messages=messages,
                model=config.default_vision_model,
                temperature=0.1,
                max_tokens=2000
            )
        elif mime_type == 'application/pdf':
            # Extract text from PDF first
            extracted_text = extract_text_from_pdf(file_path)
            
            # Process extracted text with regular chat API
            text_prompt = f"""{base_prompt}

Hier ist der extrahierte Text aus dem PDF-Dokument:

{extracted_text}"""
            
            messages = [
                {
                    "role": "user",
                    "content": text_prompt
                }
            ]
            
            # Call OpenAI with regular text model
            response = call_openai_chat(
                messages=messages,
                model=config.default_model,
                temperature=0.1,
                max_tokens=2000
            )
        else:
            return {
                'success': False,
                'error': f'Unsupported MIME type: {mime_type}'
            }
        
        if not response.success:
            return {
                'success': False,
                'error': response.error
            }
        
        # Extract the content
        content = response.data['choices'][0]['message']['content']
        
        # Try to parse JSON from the response
        # Sometimes the model wraps JSON in markdown code blocks
        if '```json' in content:
            content = content.split('```json')[1].split('```')[0].strip()
        elif '```' in content:
            content = content.split('```')[1].split('```')[0].strip()
        
        extracted_data = json.loads(content)
        
        return {
            'success': True,
            'data': extracted_data,
            'raw_response': response.data
        }
        
    except json.JSONDecodeError as e:
        return {
            'success': False,
            'error': f'Failed to parse JSON from OpenAI response: {str(e)}',
            'raw_content': content if 'content' in locals() else None
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'Error processing document: {str(e)}'
        }


def map_to_database_objects(extracted_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map extracted data to database objects (Account, Payee, Category).
    
    Args:
        extracted_data: Dictionary with extracted information.
        
    Returns:
        dict: Mapped database objects and values.
    """
    from ..models import Account, Payee, Category
    
    result = {
        'suggested_account': None,
        'suggested_payee': None,
        'suggested_category': None,
        'suggested_amount': None,
        'suggested_currency': extracted_data.get('currency', 'EUR'),
        'suggested_date': None,
        'suggested_description': extracted_data.get('description', ''),
        'suggested_is_recurring': extracted_data.get('is_recurring', False),
        'suggestion_confidence': extracted_data.get('confidence'),
        'extracted_text': extracted_data.get('extracted_text', ''),
    }
    
    # Map payee
    payee_name = extracted_data.get('payee_name')
    if payee_name:
        from django.db.models import Q
        # Try to find existing payee using exact or partial match in one query
        payee = Payee.objects.filter(
            Q(name__iexact=payee_name) | Q(name__icontains=payee_name),
            is_active=True
        ).first()
        result['suggested_payee'] = payee
    
    # Map account
    account_name = extracted_data.get('account_name')
    if account_name:
        from django.db.models import Q
        # Try to find existing account using exact or partial match in one query
        account = Account.objects.filter(
            Q(name__iexact=account_name) | Q(name__icontains=account_name),
            is_active=True
        ).first()
        result['suggested_account'] = account
    
    # Map category
    category_name = extracted_data.get('category_name')
    if category_name:
        from django.db.models import Q
        # Try to find existing category using exact or partial match in one query
        category = Category.objects.filter(
            Q(name__iexact=category_name) | Q(name__icontains=category_name)
        ).first()
        result['suggested_category'] = category
    
    # Parse amount
    amount = extracted_data.get('amount')
    if amount is not None:
        try:
            result['suggested_amount'] = Decimal(str(amount))
        except (InvalidOperation, ValueError, TypeError):
            result['suggested_amount'] = None
    
    # Parse date
    date_str = extracted_data.get('date')
    if date_str:
        try:
            result['suggested_date'] = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            result['suggested_date'] = None
    
    return result


def process_document_upload(document_upload) -> bool:
    """
    Main function to process a DocumentUpload instance.
    
    Args:
        document_upload: DocumentUpload instance to process.
        
    Returns:
        bool: True if successful, False otherwise.
    """
    try:
        # Update status
        document_upload.status = 'AI_PROCESSING'
        document_upload.save()
        
        # Get file path
        file_path = document_upload.file.path
        mime_type = document_upload.mime_type or get_mime_type(document_upload.original_filename)
        
        # Process with OpenAI
        result = process_document_with_openai(file_path, mime_type)
        
        if not result['success']:
            document_upload.status = 'ERROR'
            document_upload.error_message = result['error']
            document_upload.save()
            return False
        
        # Store raw AI result
        document_upload.ai_result_openai = result['raw_response']
        
        # Map to database objects
        extracted_data = result['data']
        mapped_data = map_to_database_objects(extracted_data)
        
        # Update document with suggestions
        document_upload.suggested_account = mapped_data['suggested_account']
        document_upload.suggested_payee = mapped_data['suggested_payee']
        document_upload.suggested_category = mapped_data['suggested_category']
        document_upload.suggested_amount = mapped_data['suggested_amount']
        document_upload.suggested_currency = mapped_data['suggested_currency']
        document_upload.suggested_date = mapped_data['suggested_date']
        document_upload.suggested_description = mapped_data['suggested_description']
        document_upload.suggested_is_recurring = mapped_data['suggested_is_recurring']
        document_upload.suggestion_confidence = mapped_data['suggestion_confidence']
        document_upload.extracted_text = mapped_data['extracted_text']
        
        # Update status
        document_upload.status = 'REVIEW_PENDING'
        document_upload.save()
        
        return True
        
    except Exception as e:
        document_upload.status = 'ERROR'
        document_upload.error_message = f'Unexpected error: {str(e)}'
        document_upload.save()
        return False
