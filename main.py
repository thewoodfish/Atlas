"""
Atlas entry point.

Usage:
    python main.py               # run the full autonomous loop + dashboard
    python main.py --no-dashboard
    python main.py --demo        # run the demo scenario (1000 USDT seed)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from loguru import logger

from config import config


def _configure_logging() -> None:
    log_path = Path(config.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(
        sys.stderr,
        level=config.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>",
        colorize=True,
    )
    logger.add(
        str(log_path),
        level=config.log_level,
        rotation="10 MB",
        retention="7 days",
        compression="zip",
    )


async def _preflight_check() -> None:
    """
    Validate that the Anthropic API key is reachable before starting the demo.
    Fails fast with a clear error rather than surfacing 30 seconds into a cycle.
    """
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
    try:
        logger.info("Preflight: verifying Anthropic API key…")
        await asyncio.wait_for(
            client.messages.create(
                model=config.claude_model,
                max_tokens=8,
                messages=[{"role": "user", "content": "ping"}],
            ),
            timeout=15,
        )
        logger.info("Preflight: Anthropic API key OK")
    except asyncio.TimeoutError:
        logger.error("Preflight FAILED: Anthropic API timed out (15 s). Check network.")
        sys.exit(1)
    except anthropic.AuthenticationError:
        logger.error("Preflight FAILED: Invalid ANTHROPIC_API_KEY.")
        sys.exit(1)
    except Exception as exc:
        logger.error(f"Preflight FAILED: {exc}")
        sys.exit(1)


async def run(demo: bool = False, with_dashboard: bool = True) -> None:
    from atlas.core.orchestrator import Orchestrator

    orchestrator = Orchestrator(demo=demo)

    if with_dashboard:
        import threading
        from atlas.dashboard.backend.app import create_app

        app, socketio = create_app(orchestrator=orchestrator)
        dashboard_thread = threading.Thread(
            target=lambda: socketio.run(
                app,
                host=config.dashboard_host,
                port=config.dashboard_port,
                debug=False,
                use_reloader=False,
                allow_unsafe_werkzeug=True,
            ),
            daemon=True,
        )
        dashboard_thread.start()
        logger.info(
            f"Dashboard running at http://{config.dashboard_host}:{config.dashboard_port}"
        )

    await orchestrator.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Atlas — autonomous treasury agent")
    parser.add_argument(
        "--no-dashboard", action="store_true", help="Disable the Flask dashboard"
    )
    parser.add_argument(
        "--demo", action="store_true", help="Run the demo scenario"
    )
    args = parser.parse_args()

    _configure_logging()
    logger.info("Atlas starting up")

    if not config.anthropic_api_key:
        logger.error(
            "ANTHROPIC_API_KEY is not set. Copy .env.example → .env and fill in your key."
        )
        sys.exit(1)

    async def _main() -> None:
        await _preflight_check()
        await run(demo=args.demo, with_dashboard=not args.no_dashboard)

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        logger.info("Atlas shut down gracefully.")


if __name__ == "__main__":
    main()
