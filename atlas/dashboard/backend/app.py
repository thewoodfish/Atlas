"""
Flask application factory for the Atlas dashboard backend.

Usage
-----
    from atlas.dashboard.backend.app import create_app
    app, socketio = create_app()
    socketio.run(app, host="0.0.0.0", port=5000)

The optional `orchestrator` argument wires the live Orchestrator instance
into the app so all API endpoints serve real data instead of demo data.
"""
from __future__ import annotations

import time
from typing import Optional

from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO

from atlas.dashboard.backend.api import (
    api,
    register_socketio_events,
    start_event_forwarder,
)
from config import config


def create_app(orchestrator=None) -> tuple[Flask, SocketIO]:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "atlas-dashboard-secret"
    app.config["ORCHESTRATOR"] = orchestrator
    app.config["START_TIME"] = time.time()

    # CORS — allow all origins for local frontend dev
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # SocketIO with simple-websocket transport
    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode="threading",
        logger=False,
        engineio_logger=False,
        path="/ws",
    )

    # Register REST blueprint
    app.register_blueprint(api)

    # Register WebSocket events
    register_socketio_events(socketio)

    # Start background thread that forwards orchestrator events to WS clients
    if orchestrator is not None:
        start_event_forwarder(socketio, app)

    @app.route("/health")
    def health():
        return {"status": "ok", "uptime": round(time.time() - app.config["START_TIME"], 1)}

    return app, socketio
