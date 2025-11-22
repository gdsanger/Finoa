"""
OpenAI client for direct API access.
Used for special use cases like vision/document recognition.
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import requests
from django.core.exceptions import ImproperlyConfigured


@dataclass
class OpenAIResponse:
    """Response wrapper for OpenAI API calls."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    status_code: Optional[int] = None


def get_active_openai_config():
    """
    Get the active OpenAI configuration.
    
    Returns:
        OpenAIConfig: The active configuration instance.
        
    Raises:
        ImproperlyConfigured: If no active configuration exists.
    """
    from ..models import OpenAIConfig
    
    config = OpenAIConfig.objects.filter(is_active=True).first()
    if not config:
        raise ImproperlyConfigured(
            "No active OpenAI configuration found. Please configure OpenAI in the admin panel."
        )
    return config


def call_openai_chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    additional_params: Optional[Dict[str, Any]] = None
) -> OpenAIResponse:
    """
    Call OpenAI Chat Completion API.
    
    Args:
        messages: List of message dicts with 'role' and 'content' keys.
                 Example: [{"role": "user", "content": "Hello"}]
        model: Model to use (uses default from config if not provided).
        temperature: Temperature for response generation (default: 0.7).
        max_tokens: Maximum tokens for response (optional).
        additional_params: Additional parameters to pass to the API.
        
    Returns:
        OpenAIResponse: Response object with success status, data, or error information.
    """
    try:
        config = get_active_openai_config()
        
        # Build request payload
        payload = {
            "model": model or config.default_model,
            "messages": messages,
            "temperature": temperature,
        }
        
        if max_tokens:
            payload["max_tokens"] = max_tokens
        
        # Add any additional parameters
        if additional_params:
            payload.update(additional_params)
        
        # Make API request
        url = f"{config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=config.timeout_seconds
        )
        
        # Handle response
        if response.status_code == 200:
            return OpenAIResponse(
                success=True,
                data=response.json(),
                status_code=response.status_code
            )
        else:
            return OpenAIResponse(
                success=False,
                error=f"API returned status {response.status_code}: {response.text}",
                status_code=response.status_code
            )
            
    except ImproperlyConfigured as e:
        return OpenAIResponse(
            success=False,
            error=str(e)
        )
    except requests.Timeout:
        return OpenAIResponse(
            success=False,
            error="Request timeout - OpenAI did not respond in time"
        )
    except requests.RequestException as e:
        return OpenAIResponse(
            success=False,
            error=f"Request failed: {str(e)}"
        )
    except Exception as e:
        return OpenAIResponse(
            success=False,
            error=f"Unexpected error: {str(e)}"
        )
