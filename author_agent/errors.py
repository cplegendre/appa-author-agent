from __future__ import annotations


class AuthorAgentError(Exception):
    """Base class for expected, user-actionable Author Agent failures."""


class ConfigError(AuthorAgentError, ValueError):
    """Configuration is missing or invalid."""


class ValidationError(AuthorAgentError, ValueError):
    """User input or persisted local data failed validation."""


class SocialFormattingError(ValidationError):
    """Base class for mechanical social-copy formatting failures.

    Covers failures that are cheap to retry harder for and safe to
    auto-correct in code (not regenerate from scratch) if the model still
    won't comply after extra corrective retries.
    """


class MarkdownFormattingError(SocialFormattingError):
    """Social copy contained Markdown emphasis/heading/bullet syntax."""


class ParagraphFormattingError(SocialFormattingError):
    """Long social copy was returned as one unbroken block with no \\n\\n breaks."""


class OllamaError(AuthorAgentError, RuntimeError):
    """Ollama could not satisfy a request."""


class RagError(AuthorAgentError, RuntimeError):
    """RAG storage or retrieval failed."""


class WebsiteError(AuthorAgentError, RuntimeError):
    """Website/calendar/git operation failed."""
