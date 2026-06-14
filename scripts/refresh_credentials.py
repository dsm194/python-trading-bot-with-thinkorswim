#!/usr/bin/env python3
"""Refresh Gmail and Schwab credentials without starting the trading loop."""

import argparse
import asyncio
import logging
import os
import shutil
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

import config_loader  # noqa: E402,F401
from async_mongo import AsyncMongoDB  # noqa: E402
from gmail import Gmail  # noqa: E402
from tdameritrade import TDAmeritrade  # noqa: E402


class NullPushNotification:
    def send(self, _notification):
        return None


def backup_file(path: Path, force: bool) -> Path | None:
    if not force or not path.exists():
        return None

    backup = path.with_suffix(path.suffix + ".refresh-backup")
    shutil.copy2(path, backup)
    path.unlink()
    return backup


def finish_backup(path: Path, backup: Path | None, success: bool) -> None:
    if backup is None:
        return
    if success:
        backup.unlink(missing_ok=True)
    else:
        shutil.move(backup, path)


async def refresh_schwab(logger: logging.Logger, force: bool) -> bool:
    token_path = Path(
        os.getenv("SCHWAB_TOKEN_PATH", ROOT_DIR / "tmp" / "token.json")
    ).expanduser()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    backup = backup_file(token_path, force)
    mongo = AsyncMongoDB(logger)
    success = False

    try:
        if not await mongo.connect():
            return False

        refreshed_accounts = 0
        async for user in mongo.users.find({}):
            for account_id in user.get("Accounts", {}):
                client = TDAmeritrade(
                    mongo,
                    user,
                    account_id,
                    logger,
                    NullPushNotification(),
                )
                if await client.initialConnect():
                    refreshed_accounts += 1

        success = refreshed_accounts > 0 and token_path.is_file()
        if not success:
            logger.error("No Schwab account completed authorization.")
        return success
    finally:
        await mongo.close()
        finish_backup(token_path, backup, success)


def refresh_gmail(logger: logging.Logger, force: bool) -> bool:
    token_path = Path(
        os.getenv(
            "GMAIL_TOKEN_PATH",
            ROOT_DIR / "gmail" / "creds" / "token.json",
        )
    ).expanduser()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    backup = backup_file(token_path, force)
    success = False

    try:
        success = Gmail(logger).connect()
        return success
    finally:
        finish_backup(token_path, backup, success)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force",
        action="store_true",
        help="Perform fresh interactive authorization for both providers.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logger = logging.getLogger("credential-refresh")

    if not refresh_gmail(logger, args.force):
        return 1
    if not await refresh_schwab(logger, args.force):
        return 1

    logger.info("Gmail and Schwab credentials refreshed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
