from qt.core import QIcon

PLUGIN_ICON = 'images/icon.png'
PLUGIN_ICON_DARK = 'images/icon_dark.png'


def plugin_icon():
    try:
        # `get_icons` is injected by calibre into plugin zip modules at
        # exec time; not available when running outside a loaded plugin
        # zip (e.g. during standalone testing).
        return get_icons(_icon_name())  # noqa: F821
    except Exception:
        return QIcon()


def _icon_name():
    try:
        from calibre.gui2 import is_dark_theme
        if is_dark_theme():
            return PLUGIN_ICON_DARK
    except Exception:
        # older calibre without is_dark_theme(), or no QApplication yet --
        # fall back to the light-theme icon either way.
        pass
    return PLUGIN_ICON
