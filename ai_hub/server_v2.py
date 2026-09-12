"""Versioned local API entry point for the AI Hub desktop compatibility surface.

The product is the native Windows desktop app; this module keeps the legacy
local HTTP surface available for diagnostics and existing callers.
"""

from .server import AIHubHandler, APIError, create_server

__all__ = ["AIHubHandler", "APIError", "create_server"]
