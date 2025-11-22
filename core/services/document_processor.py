"""
Document processor for AI-powered analysis of receipts and invoices.
Uses OpenAI Vision API for text extraction from images and PyMuPDF for PDFs.
Sends extracted text to KIGate agent for metadata extraction.
"""
import base64
import json
import re
from typing import Dict, Any, Optional
from decimal import Decimal, InvalidOperation
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF
from dateutil import parser

from django.core.files.uploadedfile import UploadedFile

from .openai_client import call_openai_chat, get_active_openai_config
from .kigate_client import execute_agent


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


def sanitize_extracted_text(text: str) -> str:
    """
    Sanitize extracted text to prevent prompt injection.
    
    Args:
        text: The raw extracted text.
        
    Returns:
        str: Sanitized text with potentially harmful patterns removed.
    """
    # Remove null bytes and other control characters except common ones (newline, tab, carriage return)
    sanitized = ''.join(char for char in text if char >= ' ' or char in '\n\t\r')
    
    # Remove excessive whitespace
    sanitized = '\n'.join(line.strip() for line in sanitized.split('\n') if line.strip())
    
    return sanitized


def extract_text_from_pdf(file_path: str, max_chars: int = 50000, max_file_size_mb: int = 50) -> str:
    """
    Extract text from a PDF file using PyMuPDF.
    
    Args:
        file_path: Path to the PDF file.
        max_chars: Maximum number of characters to extract (default: 50000).
        max_file_size_mb: Maximum file size in MB to process (default: 50).
        
    Returns:
        str: Extracted and sanitized text from the PDF, truncated if it exceeds max_chars.
        
    Raises:
        FileNotFoundError: If the PDF file doesn't exist.
        ValueError: If the PDF file is too large.
        RuntimeError: If PDF extraction fails.
    """
    try:
        # Check file size before processing
        file_size_mb = Path(file_path).stat().st_size / (1024 * 1024)
        if file_size_mb > max_file_size_mb:
            raise ValueError(f"PDF file is too large ({file_size_mb:.1f} MB). Maximum allowed is {max_file_size_mb} MB.")
        
        with fitz.open(file_path) as doc:
            text_parts = []
            total_chars = 0
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                page_text = page.get_text()
                
                # Stop if we've reached the character limit
                remaining_chars = max_chars - total_chars
                if remaining_chars <= 0:
                    break
                
                if len(page_text) > remaining_chars:
                    text_parts.append(page_text[:remaining_chars])
                    break
                
                text_parts.append(page_text)
                total_chars += len(page_text)
            
            raw_text = '\n'.join(text_parts)
            return sanitize_extracted_text(raw_text)
    except FileNotFoundError:
        raise
    except ValueError:
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


def process_document_with_kigate(file_path: str, mime_type: str) -> Dict[str, Any]:
    """
    Process a document using KIGate agent to extract booking information.
    For images: uses OpenAI Vision API to extract text first.
    For PDFs: extracts text with PyMuPDF.
    Then sends extracted text to KIGate agent "invoice-metadata-extractor-de".
    
    Args:
        file_path: Path to the document file.
        mime_type: MIME type of the document.
        
    Returns:
        dict: Extracted information or error details.
    """
    try:
        # Step 1: Extract text from document
        extracted_text = ""
        
        if is_image_mime_type(mime_type):
            # For images, use OpenAI Vision API to extract text
            config = get_active_openai_config()
            base64_content = encode_file_to_base64(file_path)
            
            # Simple prompt to extract text from image
            text_extraction_prompt = "Extrahiere den gesamten lesbaren Text aus diesem Bild. Gib nur den Text zurück, ohne zusätzliche Erklärungen."
            
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": text_extraction_prompt
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
            
            # Call OpenAI Vision API to extract text
            response = call_openai_chat(
                messages=messages,
                model=config.default_vision_model,
                temperature=0.1,
                max_tokens=2000
            )
            
            if not response.success:
                return {
                    'success': False,
                    'error': f'Failed to extract text from image: {response.error}'
                }
            
            extracted_text = response.data['choices'][0]['message']['content']
            
        elif mime_type == 'application/pdf':
            # Extract text from PDF
            extracted_text = extract_text_from_pdf(file_path)
        else:
            return {
                'success': False,
                'error': f'Unsupported MIME type: {mime_type}'
            }
        
        # Step 2: Send extracted text to KIGate agent
        kigate_response = execute_agent(
            prompt=extracted_text,
            agent_name="invoice-metadata-extractor-de"
        )
        
        if not kigate_response.success:
            return {
                'success': False,
                'error': f'KIGate agent failed: {kigate_response.error}'
            }
        
        # Step 3: Parse the response
        # KIGate returns the result in the 'result' field
        result_text = kigate_response.data.get('result', '')
        
        # Try to parse JSON from the response
        # Sometimes the model wraps JSON in markdown code blocks
        if '```json' in result_text:
            result_text = result_text.split('```json')[1].split('```')[0].strip()
        elif '```' in result_text:
            result_text = result_text.split('```')[1].split('```')[0].strip()
        
        kigate_data = json.loads(result_text)
        
        # Step 4: Convert German field names to internal format
        # Expected KIGate response format:
        # {
        #   "Belegnummer": "DE52E6ZDABEY",
        #   "Absender": "Amazon Business EU S.à r.l.",
        #   "Betrag": "27,03 €",
        #   "Fällig": "13. Dezember 2025",
        #   "Info": "Schlitzer Neutralalkohol"
        # }
        
        # Parse amount from German format (e.g., "27,03 €" or "1.234,56 €")
        amount_str = kigate_data.get('Betrag', '')
        amount = None
        currency = 'EUR'
        if amount_str:
            # Extract number and currency
            amount_match = re.search(r'([\d.,]+)\s*([€$£]|\w{3})?', amount_str)
            if amount_match:
                number_part = amount_match.group(1)
                
                # German number format uses:
                # - dot (.) as thousands separator: 1.234
                # - comma (,) as decimal separator: 27,03
                # So we need to:
                # 1. Remove dots (thousands separators)
                # 2. Replace comma with dot (decimal point)
                # But only if there's a comma (otherwise it's an integer or already in standard format)
                
                if ',' in number_part:
                    # German format: remove dots, replace comma with dot
                    number_part = number_part.replace('.', '').replace(',', '.')
                elif '.' in number_part:
                    # Check if this is a thousands separator or decimal point
                    # If there are multiple dots, they're thousands separators
                    # If only one dot and less than 3 digits after, it's decimal point
                    parts = number_part.split('.')
                    if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) > 2):
                        # Multiple dots or more than 2 decimals -> thousands separator
                        number_part = number_part.replace('.', '')
                    # else: single dot with 1-2 decimals -> keep as is (already standard format)
                
                try:
                    amount = float(number_part)
                except ValueError:
                    amount = None
                
                # Try to detect currency
                currency_part = amount_match.group(2)
                if currency_part == '€':
                    currency = 'EUR'
                elif currency_part == '$':
                    currency = 'USD'
                elif currency_part == '£':
                    currency = 'GBP'
                elif currency_part and len(currency_part) == 3:
                    currency = currency_part
        
        # Parse date from German format (e.g., "13. Dezember 2025")
        date_str = kigate_data.get('Fällig', '')
        parsed_date = None
        if date_str:
            try:
                # Try to parse German date format
                # Map German month names to English for parsing
                german_months = {
                    'Januar': 'January', 'Februar': 'February', 'März': 'March',
                    'April': 'April', 'Mai': 'May', 'Juni': 'June',
                    'Juli': 'July', 'August': 'August', 'September': 'September',
                    'Oktober': 'October', 'November': 'November', 'Dezember': 'December'
                }
                date_str_english = date_str
                for de, en in german_months.items():
                    date_str_english = date_str_english.replace(de, en)
                parsed_date = parser.parse(date_str_english, dayfirst=True).strftime('%Y-%m-%d')
            except Exception:
                parsed_date = None
        
        # Build description from Belegnummer + Info
        belegnummer = kigate_data.get('Belegnummer', '')
        info = kigate_data.get('Info', '')
        description = f"{belegnummer} {info}".strip() if belegnummer or info else ''
        
        # Convert to internal format
        extracted_data = {
            'payee_name': kigate_data.get('Absender'),
            'account_name': None,  # Not provided by KIGate agent
            'category_name': None,  # Not provided by KIGate agent
            'amount': amount,
            'currency': currency,
            'date': parsed_date,
            'description': description,
            'is_recurring': False,  # Not provided by KIGate agent
            'confidence': 0.8,  # Default confidence for KIGate
            'extracted_text': extracted_text
        }
        
        return {
            'success': True,
            'data': extracted_data,
            'raw_response': kigate_response.data
        }
        
    except json.JSONDecodeError as e:
        return {
            'success': False,
            'error': f'Failed to parse JSON from KIGate response: {str(e)}',
            'raw_content': result_text if 'result_text' in locals() else None
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'Error processing document with KIGate: {str(e)}'
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
        
        # Process with KIGate
        result = process_document_with_kigate(file_path, mime_type)
        
        if not result['success']:
            document_upload.status = 'ERROR'
            document_upload.error_message = result['error']
            document_upload.save()
            return False
        
        # Store raw AI result from KIGate
        document_upload.ai_result_kigate = result['raw_response']
        
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
