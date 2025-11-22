"""
KIGate client for AI-based text processing and agent execution.
Handles communication with KIGate API for categorization, agents, forecasts, etc.
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any
import requests
from django.core.exceptions import ImproperlyConfigured


@dataclass
class KIGateResponse:
    """Response wrapper for KIGate API calls."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    status_code: Optional[int] = None


def get_active_kigate_config():
    """
    Get the active KIGate configuration.
    
    Returns:
        KIGateConfig: The active configuration instance.
        
    Raises:
        ImproperlyConfigured: If no active configuration exists.
    """
    from ..models import KIGateConfig
    
    config = KIGateConfig.objects.filter(is_active=True).first()
    if not config:
        raise ImproperlyConfigured(
            "No active KIGate configuration found. Please configure KIGate in the admin panel."
        )
    return config


def execute_agent(
    prompt: str,
    agent_name: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    user_id: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: float = 0.7,
    additional_params: Optional[Dict[str, Any]] = None
) -> KIGateResponse:
    """
    Execute a text-based agent call through KIGate.
    
    Args:
        prompt: The user prompt/query to send to the agent.
        agent_name: Agent name (uses default from config if not provided).
        provider: AI provider name (uses default from config if not provided).
        model: Model name (uses default from config if not provided).
        user_id: User ID for the request (uses default from config if not provided).
        max_tokens: Maximum tokens for response (uses default from config if not provided).
        temperature: Temperature for response generation (default: 0.7).
        additional_params: Additional parameters to pass to the API.
        
    Returns:
        KIGateResponse: Response object with success status, data, or error information.
    """
    try:
        config = get_active_kigate_config()
        
        # Build request payload
        payload = {
            "prompt": prompt,
            "agent_name": agent_name or config.default_agent_name,
            "provider": provider or config.default_provider,
            "model": model or config.default_model,
            "user_id": user_id or config.default_user_id,
            "max_tokens": max_tokens or config.max_tokens,
            "temperature": temperature,
        }
        
        # Add any additional parameters
        if additional_params:
            payload.update(additional_params)
        
        # Remove None values but keep falsy values like 0 or empty strings
        payload = {k: v for k, v in payload.items() if v is not None}
        
        # Make API request
        url = f"{config.base_url.rstrip('/')}/agent/execute"
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
            return KIGateResponse(
                success=True,
                data=response.json(),
                status_code=response.status_code
            )
        else:
            return KIGateResponse(
                success=False,
                error=f"API returned status {response.status_code}: {response.text}",
                status_code=response.status_code
            )
            
    except ImproperlyConfigured as e:
        return KIGateResponse(
            success=False,
            error=str(e)
        )
    except requests.Timeout:
        return KIGateResponse(
            success=False,
            error="Request timeout - KIGate did not respond in time"
        )
    except requests.RequestException as e:
        return KIGateResponse(
            success=False,
            error=f"Request failed: {str(e)}"
        )
    except Exception as e:
        return KIGateResponse(
            success=False,
            error=f"Unexpected error: {str(e)}"
        )
