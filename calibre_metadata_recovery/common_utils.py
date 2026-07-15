from qt.core import QIcon

PLUGIN_ICON = 'images/icon.png'


def plugin_icon():
    try:
        # `get_icons` is injected by calibre into plugin zip modules at
        # exec time; not available when running outside a loaded plugin
        # zip (e.g. during standalone testing).
        return get_icons(PLUGIN_ICON)  # noqa: F821
    except (NameError, Exception):
        return QIcon()
