"""CAPTCHA and 2FA detection for Playwright form submissions.

Checks the current page for common blocking elements (reCAPTCHA, hCaptcha,
Cloudflare challenge, generic CAPTCHA, 2FA prompts, login redirects) and
returns a label string so the pipeline can pause for human intervention.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Ordered list: (selectors, label).  First match wins.
_BLOCKING_CHECKS: list[tuple[list[str], str]] = [
    (
        ['iframe[src*="recaptcha"]', "div.g-recaptcha"],
        "recaptcha",
    ),
    (
        ['iframe[src*="hcaptcha"]', "div.h-captcha"],
        "hcaptcha",
    ),
    (
        ['iframe[src*="challenges.cloudflare.com"]', "#challenge-running"],
        "cloudflare",
    ),
    (
        ['[class*="captcha" i]', '[id*="captcha" i]'],
        "generic_captcha",
    ),
    (
        [
            'input[name*="otp"]',
            'input[name*="verification_code"]',
            '[class*="two-factor"]',
        ],
        "2fa",
    ),
]

_LOGIN_URL_FRAGMENTS = ("/login", "/signin", "/sso")


async def detect_blocking_element(page) -> str | None:
    """Return a label for the first blocking element found, or ``None``.

    Checks selectors in priority order (reCAPTCHA > hCaptcha > Cloudflare >
    generic CAPTCHA > 2FA), then inspects the URL for login redirects.
    """
    for selectors, label in _BLOCKING_CHECKS:
        for sel in selectors:
            try:
                if await page.locator(sel).count() > 0:
                    logger.info("Blocking element detected: %s (selector: %s)", label, sel)
                    return label
            except Exception:  # noqa: BLE001
                continue

    # Check for login redirect
    url = page.url.lower() if hasattr(page, "url") else ""
    for fragment in _LOGIN_URL_FRAGMENTS:
        if fragment in url:
            logger.info("Login redirect detected: %s", url)
            return "login_required"

    return None
