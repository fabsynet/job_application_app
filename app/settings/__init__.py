"""Settings service package — single-row Settings accessor."""

from app.settings.service import get_setting, get_settings_row, set_setting

__all__ = ["get_settings_row", "set_setting", "get_setting"]
