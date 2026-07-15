# Minimal stand-in for calibre.customize, used ONLY so
# calibre_metadata_recovery/__init__.py can be imported outside a real
# Calibre installation (for unit-testing the pure-Python extraction /
# mapping / serialization logic in mapping.py, serialize.py, extractors/*).
# Not part of the shipped plugin.


class InterfaceActionBase:
    pass
