"""
Atlas entry point.

Usage:
    python main.py               # run the full autonomous loop + dashboard
    python main.py --demo        # run the demo scenario (2 cycles, market shock)
    python main.py --no-agent    # dashboard + API only, no orchestrator (Railway/Vercel preview)
    python main.py --no-dashboard
"""
from __future__ import annotations

import argparse
import asyncio
import os
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
    except anthropic.RateLimitError:
        logger.warning("Preflight: rate limit hit — API key valid, continuing.")
    except Exception as exc:
        logger.error(f"Preflight FAILED: {exc}")
        sys.exit(1)


async def run(
    demo: bool = False,
    with_dashboard: bool = True,
    with_agent: bool = True,
    max_cycles: int | None = None,
) -> None:
    from atlas.core.orchestrator import Orchestrator
    from atlas.dashboard.backend.app import create_app

    # In no-agent mode pass orchestrator=None so the dashboard serves demo data
    orchestrator = Orchestrator(demo=demo, max_cycles=max_cycles) if with_agent else None

    if with_dashboard:
        import threading

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

    if with_agent:
        await orchestrator.run()

    # Keep the dashboard alive even after the orchestrator stops (e.g. --max-cycles)
    logger.info("Agent stopped. Dashboard still running — press Ctrl+C to quit.")
    await asyncio.Event().wait()


def main() -> None:
    parser = argparse.ArgumentParser(description="Atlas — autonomous treasury agent")
    parser.add_argument(
        "--no-dashboard", action="store_true", help="Disable the Flask dashboard"
    )
    parser.add_argument(
        "--demo", action="store_true", help="Run the demo scenario"
    )
    parser.add_argument(
        "--no-agent", action="store_true",
        help="Start dashboard + API only; skip the orchestrator (no Anthropic calls)"
    )
    parser.add_argument(
        "--max-cycles", type=int, default=None, help="Stop after N cycles (default: run forever)"
    )
    parser.add_argument(
        "--offline", action="store_true",
        help="Skip all Claude API calls; use rule-based logic with live DeFiLlama data"
    )
    args = parser.parse_args()

    if args.offline:
        os.environ["ATLAS_OFFLINE"] = "true"
        # Re-read config so the singleton picks up the flag
        config.offline_mode = True

    _configure_logging()
    logger.info("Atlas starting up" + (" [OFFLINE MODE — no Claude calls]" if config.offline_mode else ""))

    # --no-agent: skip API key check and orchestrator entirely
    if args.no_agent:
        async def _main() -> None:
            await run(with_dashboard=True, with_agent=False)
        try:
            asyncio.run(_main())
        except KeyboardInterrupt:
            logger.info("Atlas shut down gracefully.")
        return

    # --offline: skip API key check too
    if config.offline_mode:
        async def _main() -> None:  # type: ignore[no-redef]
            await run(demo=args.demo, with_dashboard=not args.no_dashboard, max_cycles=args.max_cycles)
        try:
            asyncio.run(_main())
        except KeyboardInterrupt:
            logger.info("Atlas shut down gracefully.")
        return

    if not config.anthropic_api_key:
        logger.error(
            "ANTHROPIC_API_KEY is not set. Copy .env.example → .env and fill in your key."
        )
        sys.exit(1)

    async def _main() -> None:
        await _preflight_check()
        await run(demo=args.demo, with_dashboard=not args.no_dashboard, max_cycles=args.max_cycles)

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        logger.info("Atlas shut down gracefully.")


if __name__ == "__main__":
    main()
