"""Version information for hvcwatch."""

import os


def get_git_commit() -> str:
    """Get the git commit hash from environment variable.

    Returns:
        Git commit hash (short or full), or 'unknown' if not set.
    """
    return os.getenv("GIT_COMMIT", "unknown")


def get_git_branch() -> str:
    """Get the git branch name from environment variable.

    Returns:
        Git branch name, or 'unknown' if not set.
    """
    return os.getenv("GIT_BRANCH", "unknown")


def get_version_info() -> str:
    """Get formatted version information for logging.

    Returns:
        Formatted string with git commit and branch info.
    """
    commit = get_git_commit()
    branch = get_git_branch()
    return f"commit={commit}, branch={branch}"
