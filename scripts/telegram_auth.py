from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Load .env from the backend directory, regardless of where the script is invoked from.
# python-dotenv is available as a transitive dependency of pydantic-settings.
_SCRIPTS_DIR = Path(__file__).parent
_BACKEND_DIR = _SCRIPTS_DIR.parent / "backend"

try:
    from dotenv import load_dotenv

    # .env lives in the project root (parent of backend/), matching config.py resolution.
    _env_file = _BACKEND_DIR.parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
    else:
        # Fall back to cwd .env (e.g. when invoked from project root directly)
        load_dotenv()
except ImportError:
    # dotenv not installed — rely on environment variables being pre-set
    pass

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _read_env() -> tuple[int, str, str]:
    """Read and validate the three required Telegram settings from environment."""
    raw_api_id = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    _raw_session = os.environ.get("TELEGRAM_SESSION_PATH", "sessions/telegram.session").strip()
    # Mirror the same resolution logic as config.py: relative paths are anchored
    # to backend/ so the session file is always in the same location regardless
    # of the working directory this script is invoked from.
    _p = Path(_raw_session)
    session_path = str(_p if _p.is_absolute() else _BACKEND_DIR / _p)

    if not raw_api_id:
        print("ERROR: TELEGRAM_API_ID is not set.")
        print("  Set it in .env (project root) or export it as an environment variable.")
        sys.exit(1)

    try:
        api_id = int(raw_api_id)
    except ValueError:
        print(f"ERROR: TELEGRAM_API_ID must be an integer, got: {raw_api_id!r}")
        sys.exit(1)

    if not api_hash:
        print("ERROR: TELEGRAM_API_HASH is not set.")
        print("  Set it in .env (project root) or export it as an environment variable.")
        sys.exit(1)

    return api_id, api_hash, session_path


async def _authenticate(api_id: int, api_hash: str, session_path: str) -> None:
    """Start a Telethon session, prompting the user for credentials interactively."""
    try:
        from telethon import TelegramClient
        from telethon.errors import ApiIdInvalidError, AuthKeyError, FloodWaitError
    except ImportError:
        print("ERROR: telethon is not installed. Run: uv sync")
        sys.exit(1)

    # Ensure the sessions directory exists before Telethon tries to write the file.
    session_file = Path(session_path)
    session_file.parent.mkdir(parents=True, exist_ok=True)

    print()
    print("WontHurtMaps — Telegram Authentication")
    print("=" * 40)
    print(f"Session file : {session_file.resolve()}")
    print()
    print("Telethon will now prompt you for:")
    print("  1. Your phone number (international format, e.g. +380501234567)")
    print("  2. The verification code sent to your Telegram account")
    print("  3. Your 2FA password (only if two-step verification is enabled)")
    print()

    client = TelegramClient(str(session_file), api_id, api_hash)

    try:
        await client.start()

        me = await client.get_me()
        if me is None:
            print("WARNING: Authentication appeared to succeed but could not fetch account info.")
        else:
            name = " ".join(filter(None, [me.first_name, me.last_name]))
            phone = getattr(me, "phone", "unknown")
            print()
            print("Authentication successful.")
            print(f"  Account : {name}")
            print(f"  Phone   : +{phone}")
            print(f"  Session : {session_file.resolve()}")
            print()
            print("You can now run the worker. The session will be reused automatically.")

    except ApiIdInvalidError:
        print()
        print("ERROR: The API ID / API hash combination is invalid.")
        print("  Verify your credentials at https://my.telegram.org/apps")
        sys.exit(1)
    except AuthKeyError:
        print()
        print("ERROR: Authentication key error. The session file may be corrupted.")
        print(f"  Try deleting {session_file.resolve()} and running this script again.")
        sys.exit(1)
    except FloodWaitError as exc:
        print()
        print(f"ERROR: Telegram rate limit hit. Wait {exc.seconds} seconds before retrying.")
        sys.exit(1)
    except EOFError:
        # Raised when stdin is not interactive (e.g. piped input ends unexpectedly).
        print()
        print("ERROR: No input received. This script requires an interactive terminal.")
        sys.exit(1)
    except OSError as exc:
        print()
        print(f"ERROR: Network error: {exc}")
        print("  Check your internet connection and try again.")
        sys.exit(1)
    finally:
        if client.is_connected():
            await client.disconnect()


def main() -> None:
    api_id, api_hash, session_path = _read_env()
    try:
        asyncio.run(_authenticate(api_id, api_hash, session_path))
    except KeyboardInterrupt:
        print()
        print("Interrupted. No session was saved.")
        sys.exit(0)


if __name__ == "__main__":
    main()
