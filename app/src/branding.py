"""User-facing workspace name, independent of stable storage and CLI identities."""

WORKSPACE_NAME = "Paul工作台"
WORKSPACE_APP = WORKSPACE_NAME + ".app"
WORKSPACE_RELEASES = "https://github.com/paulussamvel-lang/Lulu/releases"


def workspace_name():
    from .edition import is_experience, display_name
    return display_name() if is_experience() else WORKSPACE_NAME
