"""Gemini API rate limit tracking for shorter retries when rate limit is the only blocker."""

# Set when rate limit is hit, checked in main for shorter retry
gemini_rate_limit_hit = False


def reset_gemini_rate_limit_flag():
    """Reset the rate limit flag at the start of each processing cycle."""
    global gemini_rate_limit_hit
    gemini_rate_limit_hit = False


def mark_gemini_rate_limit_hit():
    """Mark that a Gemini rate limit was hit this cycle."""
    global gemini_rate_limit_hit
    gemini_rate_limit_hit = True
