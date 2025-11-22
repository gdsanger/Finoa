"""
Management command to process uploaded documents with AI.
Processes documents in UPLOADED status and extracts booking information.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import DocumentUpload
from core.services.document_processor import process_document_upload


class Command(BaseCommand):
    help = 'Process uploaded documents with AI to extract booking information'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=10,
            help='Maximum number of documents to process in one run (default: 10)'
        )
        parser.add_argument(
            '--document-id',
            type=int,
            help='Process a specific document by ID'
        )

    def handle(self, *args, **options):
        limit = options['limit']
        document_id = options.get('document_id')
        
        if document_id:
            # Process specific document
            try:
                document = DocumentUpload.objects.get(id=document_id)
                self.stdout.write(f"Processing document {document.id}: {document.original_filename}")
                success = process_document_upload(document)
                if success:
                    self.stdout.write(self.style.SUCCESS(f"✓ Successfully processed document {document.id}"))
                else:
                    self.stdout.write(self.style.ERROR(f"✗ Failed to process document {document.id}: {document.error_message}"))
            except DocumentUpload.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Document with ID {document_id} not found"))
            return
        
        # Process all documents with UPLOADED status
        documents = DocumentUpload.objects.filter(
            status=DocumentUpload.Status.UPLOADED
        ).order_by('uploaded_at')[:limit]
        
        if not documents.exists():
            self.stdout.write(self.style.WARNING("No documents to process"))
            return
        
        self.stdout.write(f"Found {documents.count()} documents to process")
        
        success_count = 0
        error_count = 0
        
        for document in documents:
            self.stdout.write(f"\nProcessing: {document.original_filename} (ID: {document.id})")
            
            try:
                success = process_document_upload(document)
                if success:
                    success_count += 1
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Success - Status: {document.status}"))
                    if document.suggested_amount:
                        self.stdout.write(f"    Amount: {document.suggested_amount} {document.suggested_currency}")
                    if document.suggested_payee:
                        self.stdout.write(f"    Payee: {document.suggested_payee.name}")
                    if document.suggested_category:
                        self.stdout.write(f"    Category: {document.suggested_category.name}")
                else:
                    error_count += 1
                    self.stdout.write(self.style.ERROR(f"  ✗ Error: {document.error_message}"))
            except Exception as e:
                error_count += 1
                self.stdout.write(self.style.ERROR(f"  ✗ Unexpected error: {str(e)}"))
        
        # Summary
        self.stdout.write("\n" + "="*50)
        self.stdout.write(f"Processing complete:")
        self.stdout.write(self.style.SUCCESS(f"  ✓ Successful: {success_count}"))
        if error_count > 0:
            self.stdout.write(self.style.ERROR(f"  ✗ Failed: {error_count}"))
        self.stdout.write("="*50)
