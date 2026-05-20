"""Media broker (T5-05).

Resolves media operations (vision, embeddings, future
video-generation) to a provider via the T5-01 capability
manifest, with a local-first default. Sits between the
caller (vision tool, differentiated MCP surface) and the
provider registry — neither side hardcodes "use anthropic
for images" or similar; both go through
:class:`MediaRegistry.backend_for(capability)`.
"""

from .registry import MediaRegistry

__all__ = ["MediaRegistry"]
