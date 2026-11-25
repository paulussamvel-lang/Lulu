class RevisionConflict(RuntimeError):
    """A caller's base revision no longer matches the saved record."""
