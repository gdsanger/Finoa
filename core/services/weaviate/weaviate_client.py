"""
Real Weaviate Client implementation.

This module provides the RealWeaviateClient that connects to an actual
Weaviate database for production use.
"""
import logging
from typing import Any, Optional

try:
    import weaviate
    from weaviate.classes.query import Filter
    WEAVIATE_AVAILABLE = True
except ImportError:
    WEAVIATE_AVAILABLE = False
    weaviate = None

from django.conf import settings

logger = logging.getLogger(__name__)


class RealWeaviateClient:
    """
    Real implementation of Weaviate client for production use.
    
    Connects to an actual Weaviate instance and provides CRUD operations
    for the WeaviateService.
    
    Configuration:
        Set WEAVIATE_URL in Django settings to configure the connection URL.
        Optionally set WEAVIATE_API_KEY for authenticated connections.
    
    Example:
        >>> client = RealWeaviateClient()
        >>> client.connect()
        >>> obj_id = client.create_object("TestClass", {"name": "test"})
        >>> client.close()
    """
    
    def __init__(
        self,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        grpc_port: Optional[int] = None
    ):
        """
        Initialize the Weaviate client.
        
        Args:
            url: Weaviate URL. If not provided, uses WEAVIATE_URL from settings.
            api_key: API key for authentication. If not provided, uses
                     WEAVIATE_API_KEY from settings.
            grpc_port: gRPC port for Weaviate. If not provided, uses
                       WEAVIATE_GRPC_PORT from settings, or defaults to 50051.
        """
        if not WEAVIATE_AVAILABLE:
            raise ImportError(
                "weaviate-client package is not installed. "
                "Install it with: pip install weaviate-client"
            )
        
        self._url = url or getattr(settings, 'WEAVIATE_URL', '')
        self._api_key = api_key or getattr(settings, 'WEAVIATE_API_KEY', '')
        self._grpc_port = grpc_port or getattr(settings, 'WEAVIATE_GRPC_PORT', 50051)
        self._client: Optional["weaviate.WeaviateClient"] = None
    
    @property
    def is_connected(self) -> bool:
        """Check if client is connected to Weaviate."""
        return self._client is not None and self._client.is_ready()
    
    def connect(self) -> "RealWeaviateClient":
        """
        Connect to the Weaviate instance.
        
        Returns:
            self: For method chaining.
            
        Raises:
            ConnectionError: If connection fails.
        """
        if not self._url:
            raise ValueError(
                "Weaviate URL not configured. Set WEAVIATE_URL in settings "
                "or pass url parameter."
            )
        
        try:
            if self._api_key:
                auth_config = weaviate.auth.AuthApiKey(api_key=self._api_key)
                self._client = weaviate.connect_to_custom(
                    http_host=self._get_host(),
                    http_port=self._get_port(),
                    http_secure=self._is_https(),
                    grpc_host=self._get_host(),
                    grpc_port=self._get_grpc_port(),
                    grpc_secure=self._is_https(),
                    auth_credentials=auth_config,
                )
            else:
                self._client = weaviate.connect_to_custom(
                    http_host=self._get_host(),
                    http_port=self._get_port(),
                    http_secure=self._is_https(),
                    grpc_host=self._get_host(),
                    grpc_port=self._get_grpc_port(),
                    grpc_secure=self._is_https(),
                )
            
            if not self._client.is_ready():
                raise ConnectionError("Weaviate server is not ready")
            
            logger.info(f"Connected to Weaviate at {self._url}")
            return self
            
        except Exception as e:
            logger.error(f"Failed to connect to Weaviate: {e}")
            raise ConnectionError(f"Failed to connect to Weaviate: {e}") from e
    
    def close(self) -> None:
        """Close the connection to Weaviate."""
        if self._client:
            self._client.close()
            self._client = None
            logger.info("Disconnected from Weaviate")
    
    def _get_host(self) -> str:
        """Extract host from URL."""
        url = self._url.replace("http://", "").replace("https://", "")
        return url.split(":")[0].split("/")[0]
    
    def _get_port(self) -> int:
        """Extract HTTP port from URL."""
        url = self._url.replace("http://", "").replace("https://", "")
        parts = url.split(":")
        if len(parts) > 1:
            port_str = parts[1].split("/")[0]
            try:
                return int(port_str)
            except ValueError:
                pass
        # Default to 443 for HTTPS, 8080 for HTTP (Weaviate's default port)
        return 443 if self._is_https() else 8080
    
    def _get_grpc_port(self) -> int:
        """Get gRPC port from configuration."""
        return self._grpc_port
    
    def _is_https(self) -> bool:
        """Check if URL uses HTTPS."""
        return self._url.startswith("https://")
    
    def _ensure_connected(self) -> None:
        """Ensure client is connected, raise error if not."""
        if not self._client:
            raise ConnectionError(
                "Not connected to Weaviate. Call connect() first."
            )
    
    def create_object(
        self,
        class_name: str,
        properties: dict,
        object_uuid: Optional[str] = None
    ) -> str:
        """
        Create an object in Weaviate.
        
        Args:
            class_name: Name of the Weaviate class.
            properties: Object properties as dictionary.
            object_uuid: Optional UUID for the object.
            
        Returns:
            str: The UUID of the created object.
        """
        self._ensure_connected()
        
        collection = self._client.collections.get(class_name)
        
        # Clean properties - remove internal fields
        clean_props = {
            k: v for k, v in properties.items() 
            if not k.startswith('_')
        }
        
        if object_uuid:
            result = collection.data.insert(
                properties=clean_props,
                uuid=object_uuid
            )
            return str(object_uuid)
        else:
            result = collection.data.insert(properties=clean_props)
            return str(result)
    
    def get_object(
        self,
        class_name: str,
        object_uuid: str
    ) -> Optional[dict]:
        """
        Get an object by UUID.
        
        Args:
            class_name: Name of the Weaviate class.
            object_uuid: UUID of the object.
            
        Returns:
            dict or None: Object properties, or None if not found.
        """
        self._ensure_connected()
        
        try:
            collection = self._client.collections.get(class_name)
            result = collection.query.fetch_object_by_id(object_uuid)
            
            if result is None:
                return None
            
            return dict(result.properties)
            
        except Exception as e:
            logger.debug(f"Object not found: {class_name}/{object_uuid}: {e}")
            return None
    
    def query_objects(
        self,
        class_name: str,
        filters: Optional[dict] = None,
        limit: int = 100,
        offset: int = 0
    ) -> list[dict]:
        """
        Query objects with filters.
        
        Args:
            class_name: Name of the Weaviate class.
            filters: Dictionary of property filters.
            limit: Maximum number of results.
            offset: Offset for pagination.
            
        Returns:
            list[dict]: List of matching objects.
        """
        self._ensure_connected()
        
        collection = self._client.collections.get(class_name)
        
        # Build filter if provided
        weaviate_filter = None
        if filters:
            filter_parts = []
            for key, value in filters.items():
                if key.startswith('_'):
                    continue
                filter_parts.append(
                    Filter.by_property(key).equal(value)
                )
            
            if filter_parts:
                weaviate_filter = filter_parts[0]
                for fp in filter_parts[1:]:
                    weaviate_filter = weaviate_filter & fp
        
        # Execute query
        if weaviate_filter:
            result = collection.query.fetch_objects(
                filters=weaviate_filter,
                limit=limit,
                offset=offset
            )
        else:
            result = collection.query.fetch_objects(
                limit=limit,
                offset=offset
            )
        
        return [dict(obj.properties) for obj in result.objects]
    
    def delete_object(
        self,
        class_name: str,
        object_uuid: str
    ) -> bool:
        """
        Delete an object.
        
        Args:
            class_name: Name of the Weaviate class.
            object_uuid: UUID of the object to delete.
            
        Returns:
            bool: True if deleted, False otherwise.
        """
        self._ensure_connected()
        
        try:
            collection = self._client.collections.get(class_name)
            collection.data.delete_by_id(object_uuid)
            return True
        except Exception as e:
            logger.debug(f"Failed to delete object: {e}")
            return False
    
    def add_reference(
        self,
        from_class: str,
        from_uuid: str,
        from_property: str,
        to_uuid: str
    ) -> bool:
        """
        Add a cross-reference between objects.
        
        Args:
            from_class: Source class name.
            from_uuid: Source object UUID.
            from_property: Reference property name.
            to_uuid: Target object UUID.
            
        Returns:
            bool: True if reference was added successfully.
        """
        self._ensure_connected()
        
        try:
            collection = self._client.collections.get(from_class)
            collection.data.reference_add(
                from_uuid=from_uuid,
                from_property=from_property,
                to=to_uuid
            )
            return True
        except Exception as e:
            logger.debug(f"Failed to add reference: {e}")
            return False
    
    def ensure_schema(self) -> None:
        """
        Ensure all required collections exist in Weaviate.
        
        Creates collections if they don't exist based on the schema
        definition from WeaviateService.
        
        Note: In Weaviate v4, properties are auto-created when data is inserted.
        This method creates the collections with their descriptions. Cross-references
        are set up during data insertion operations.
        
        Raises:
            ConnectionError: If not connected to Weaviate.
            RuntimeError: If schema initialization fails.
        """
        self._ensure_connected()
        
        from .weaviate_service import WeaviateService
        
        schema = WeaviateService.get_schema_definition()
        try:
            existing_collections = {
                c.name for c in self._client.collections.list_all().values()
            }
        except Exception as e:
            logger.error(f"Failed to list existing collections: {e}")
            raise RuntimeError(f"Failed to list Weaviate collections: {e}") from e
        
        failed_collections = []
        for class_def in schema['classes']:
            class_name = class_def['class']
            
            if class_name in existing_collections:
                logger.debug(f"Collection {class_name} already exists")
                continue
            
            try:
                logger.info(f"Creating collection {class_name}")
                
                # Create collection with description
                # Note: In Weaviate v4, properties are auto-created on first insert.
                # References are handled through the add_reference method.
                self._client.collections.create(
                    name=class_name,
                    description=class_def.get('description', ''),
                )
            except Exception as e:
                logger.error(f"Failed to create collection {class_name}: {e}")
                failed_collections.append(class_name)
        
        if failed_collections:
            raise RuntimeError(
                f"Failed to create collections: {', '.join(failed_collections)}"
            )


def get_weaviate_client(
    use_real: Optional[bool] = None,
    url: Optional[str] = None,
    api_key: Optional[str] = None
):
    """
    Factory function to get appropriate Weaviate client.
    
    Args:
        use_real: If True, forces real client. If False, forces in-memory.
                  If None, checks WEAVIATE_URL setting.
        url: Optional Weaviate URL (only for real client).
        api_key: Optional API key (only for real client).
        
    Returns:
        Weaviate client instance (Real or InMemory).
        
    Raises:
        ConnectionError: If real client is requested but connection fails.
    """
    from .weaviate_service import InMemoryWeaviateClient
    
    if use_real is None:
        # Auto-detect based on settings
        weaviate_url = url or getattr(settings, 'WEAVIATE_URL', '')
        use_real = bool(weaviate_url)
    
    if use_real:
        if not WEAVIATE_AVAILABLE:
            logger.warning(
                "weaviate-client not installed, falling back to InMemoryClient"
            )
            return InMemoryWeaviateClient()
        
        client = RealWeaviateClient(url=url, api_key=api_key)
        try:
            client.connect()
            return client
        except ConnectionError as e:
            logger.error(f"Failed to connect to Weaviate: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error connecting to Weaviate: {e}")
            raise ConnectionError(
                f"Failed to connect to Weaviate at {url or 'configured URL'}: {e}"
            ) from e
    else:
        return InMemoryWeaviateClient()
