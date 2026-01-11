"""Version information for MUDD bot."""

from pathlib import Path

GITHUB_REPO = "frizzle-chan/mudd"
_COMMIT_FILE = Path("/app/.commit_sha")


def get_git_commit() -> str:
    """Read the git commit SHA from the commit file."""
    if _COMMIT_FILE.exists():
        return _COMMIT_FILE.read_text().strip()
    return "unknown"


def get_commit_url() -> str:
    """Get the GitHub URL for the current commit."""
    git_commit = get_git_commit()
    if git_commit == "unknown":
        return "https://github.com/frizzle-chan/mudd"
    return f"https://github.com/{GITHUB_REPO}/commit/{git_commit}"
