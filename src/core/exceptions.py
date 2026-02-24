"""
Custom exception hierarchy for SAnalysis.

All application-specific exceptions inherit from SAnalysisError,
allowing callers to catch broad or specific error types.
"""


class SAnalysisError(Exception):
    """Base exception for all SAnalysis errors."""


class ConfigError(SAnalysisError):
    """Configuration is missing, invalid, or inconsistent."""


class DataFetchError(SAnalysisError):
    """Failed to retrieve data from an external source (API, scraper)."""


class CacheError(SAnalysisError):
    """Cache read/write failure."""


class ScreenerError(SAnalysisError):
    """Error during screening pipeline execution."""


class TickerValidationError(SAnalysisError, ValueError):
    """Invalid ticker symbol provided.

    Also inherits from ValueError for backward compatibility with code
    that catches ValueError for input validation errors.
    """
