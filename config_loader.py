"""Load checked-in runtime configuration and untracked secrets."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent


def load_config() -> None:
    """Load configuration without overriding values already in the environment."""
    environment = os.getenv("BOT_ENV", "dev")
    profile_path = Path(
        os.getenv(
            "BOT_CONFIG_PROFILE",
            ROOT_DIR / "config" / "env_profiles" / f".env.{environment}",
        )
    )
    secrets_path = Path(
        os.getenv("BOT_SECRETS_FILE", ROOT_DIR / "config.secrets.env")
    )
    legacy_path = ROOT_DIR / "config.env"

    if profile_path.is_file():
        load_dotenv(profile_path, override=False)

    # Temporary migration fallback: profile values win, while missing secrets
    # can still come from the old combined config.env file.
    if legacy_path.is_file():
        load_dotenv(legacy_path, override=False)

    if secrets_path.is_file():
        load_dotenv(secrets_path, override=False)


load_config()
