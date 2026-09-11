class ScanConfigurationError(Exception):
    """Raised when a scan cannot start due to invalid configuration or state."""


class ScanTimeExceededError(Exception):
    """Raised internally when the overall scan time budget is exhausted."""
