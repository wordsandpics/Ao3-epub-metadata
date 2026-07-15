from calibre.customize import InterfaceActionBase

__version__ = (0, 1, 0)


class CalibreMetadataRecoveryBase(InterfaceActionBase):
    """
    Wrapper plugin class. The real GUI logic lives in action.py's
    CalibreMetadataRecoveryAction, loaded lazily so calibredb/CLI usage
    doesn't need to import Qt.
    """

    name = 'Extract Epub Metadata'
    description = (
        'Extracts FanFicFare-compatible metadata from an EPUB in your '
        'Calibre library and writes it to the configured Saved Metadata '
        "column, ready for FanFicFare’s Update Calibre Metadata from "
        'Saved Metadata Column action.'
    )
    supported_platforms = ['windows', 'osx', 'linux']
    author = 'wordsandpics'
    version = __version__
    minimum_calibre_version = (5, 0, 0)

    actual_plugin = 'calibre_plugins.calibre_metadata_recovery.action:CalibreMetadataRecoveryAction'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.calibre_metadata_recovery.config import ConfigWidget
        return ConfigWidget(self.actual_plugin_)

    def save_settings(self, config_widget):
        config_widget.save_settings()
