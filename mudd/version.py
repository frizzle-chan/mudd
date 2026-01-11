"""Version information for MUDD bot."""

# This will be set at build time via Dockerfile
GIT_COMMIT = "unknown"
GITHUB_REPO = "frizzle-chan/mudd"


def get_commit_url() -> str:
    """Get the GitHub URL for the current commit."""
    if GIT_COMMIT == "unknown":
        return "https://github.com/frizzle-chan/mudd"
    return f"https://github.com/{GITHUB_REPO}/commit/{GIT_COMMIT}"
