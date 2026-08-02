"""Authenticated local Netmon dashboard, settings UI and data-backed chat.

The first browser visit is deliberately blocked by an administrator-password
setup screen. The password is confirmed in the browser, hashed with Werkzeug's
scrypt implementation and then discarded; only the hash is persisted.

All dashboard routes, measurement data, graph images and mutating APIs require
an authenticated session. State-changing requests additionally require a CSRF
token. Static assets and the minimal health endpoint remain public so systemd
and reverse proxies can check service health without possessing a session.

The optional Groq API key is accepted only through the authenticated settings
panel. It is tested before being stored, never returned to JavaScript, and
remains independent of Telegram or Discord (neither notifier exists here).
"""

from __future__ import annotations

import logging
import secrets
import time
from datetime import timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar, cast

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from waitress import serve

import ai
import config as cfg
import reporting
import secure_settings
import sqlite


log = logging.getLogger("netmon.web")
ViewFunction = TypeVar("ViewFunction", bound=Callable[..., Any])

AI_CHAT_SYSTEM_PROMPT = """You answer questions about a private local network.
Use only the supplied Netmon measurements. Be concise and explicit about the
time window. Never invent a cause, device identity or measurement. Plain text
only; no HTML and no Markdown tables. Do not claim to have inspected traffic
contents: Netmon measures WAN speed, latency and active IP counts only.
"""

AI_CONNECTION_TEST_PROMPT = """You are validating a Netmon API connection.
Reply with one short plain-text sentence confirming that the connection works.
Do not use tools, browse the web or include Markdown.
"""


def _serialise_snapshots(
    snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert raw bit-per-second values into browser-friendly units."""

    return [
        {
            **snapshot,
            "download_mbps": round(float(snapshot["download"]) / 1_000_000, 2),
            "upload_mbps": round(float(snapshot["upload"]) / 1_000_000, 2),
            "ping": round(float(snapshot["ping"]), 2),
        }
        for snapshot in snapshots
    ]


def _safe_ai_error(exc: Exception) -> str:
    """Return a useful error without ever echoing a supplied API key."""

    message = str(exc).strip() or exc.__class__.__name__
    return message[:500]


def _test_groq_key(
    *,
    api_key: str,
    model: str,
    base_url: str,
    request_timeout: int,
) -> str:
    """Make one small authenticated inference request before saving a key."""

    with ai.Client.init(api_key, model, base_url, request_timeout) as client:
        response = client.send_message(
            "Confirm the Netmon connection test.",
            AI_CONNECTION_TEST_PROMPT,
        )

    response = response.strip()
    if not response:
        raise RuntimeError("Groq returned an empty response.")
    return response[:300]


def create_app(conf: cfg.Config | None = None) -> Flask:
    """Application factory used by production and smoke tests."""

    configuration = conf or cfg.Config.init()
    settings_store = secure_settings.SettingsStore(
        configuration.secure_settings_path
    )
    initial_settings = settings_store.load()

    app = Flask(__name__)
    app.secret_key = initial_settings.session_secret
    app.config.update(
        NETMON_CONFIG=configuration,
        NETMON_SETTINGS_STORE=settings_store,
        MAX_CONTENT_LENGTH=16 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        # The current direct LAN endpoint is plain HTTP. This must become True
        # when the site is put behind local HTTPS, otherwise browsers will not
        # return the session cookie to the current address.
        SESSION_COOKIE_SECURE=False,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    )

    def csrf_token() -> str:
        """Return one unpredictable token bound to the signed session cookie."""

        token = session.get("csrf_token")
        if not isinstance(token, str) or not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return token

    def wants_json() -> bool:
        return request.path.startswith("/api/")

    def is_authenticated() -> bool:
        return session.get("authenticated") is True

    def login_required(view: ViewFunction) -> ViewFunction:
        """Require the initial password setup and an authenticated session."""

        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            settings = settings_store.load()
            if not settings.admin_configured:
                if wants_json():
                    return jsonify({"error": "Initial administrator setup required."}), 428
                return redirect(url_for("setup"))

            if not is_authenticated():
                if wants_json():
                    return jsonify({"error": "Authentication required."}), 401
                return redirect(url_for("login"))

            return view(*args, **kwargs)

        return cast(ViewFunction, wrapped)

    def csrf_required(view: ViewFunction) -> ViewFunction:
        """Reject cross-site state changes even when a session cookie exists."""

        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            supplied = request.headers.get("X-CSRF-Token") or request.form.get(
                "csrf_token",
                "",
            )
            expected = session.get("csrf_token")
            if (
                not isinstance(expected, str)
                or not isinstance(supplied, str)
                or not secrets.compare_digest(expected, supplied)
            ):
                if wants_json():
                    return jsonify({"error": "CSRF validation failed."}), 403
                return Response("CSRF validation failed.", status=403)
            return view(*args, **kwargs)

        return cast(ViewFunction, wrapped)

    @app.context_processor
    def inject_template_security_values() -> dict[str, str]:
        return {"csrf_token": csrf_token()}

    @app.after_request
    def add_local_security_headers(response: Response) -> Response:
        # The policy permits only this origin's CSS, JavaScript, images and API
        # calls. It deliberately excludes external scripts, frames and forms.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self'; "
            "script-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'none'; "
            "form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz")
    def health() -> Response:
        try:
            settings_store.load()
            with sqlite.DB.init(configuration.db_path) as database:
                database.get_recent_snapshots(hours=24, limit=1)
            return jsonify({"status": "ok"})
        except Exception as exc:
            log.exception("Health check failed.")
            return jsonify({"status": "error", "detail": str(exc)}), 503

    @app.route("/setup", methods=["GET", "POST"])
    def setup() -> Response | str:
        settings = settings_store.load()
        if settings.admin_configured:
            return redirect(url_for("index" if is_authenticated() else "login"))

        error = ""
        if request.method == "POST":
            supplied = request.form.get("csrf_token", "")
            expected = session.get("csrf_token", "")
            if not (
                isinstance(expected, str)
                and secrets.compare_digest(expected, supplied)
            ):
                return Response("CSRF validation failed.", status=403)

            password = request.form.get("password", "")
            confirmation = request.form.get("password_confirm", "")

            if password != confirmation:
                error = "The two password entries do not match."
            else:
                try:
                    settings_store.set_admin_password(password)
                except ValueError as exc:
                    error = str(exc)
                else:
                    # Successful setup proves possession of both matching
                    # entries, so establish the first authenticated session.
                    session.clear()
                    session.permanent = True
                    session["authenticated"] = True
                    session["csrf_token"] = secrets.token_urlsafe(32)
                    return redirect(url_for("index"))

        return render_template(
            "setup.html",
            error=error,
            minimum_length=secure_settings.MINIMUM_ADMIN_PASSWORD_LENGTH,
        )

    @app.route("/login", methods=["GET", "POST"])
    def login() -> Response | str:
        settings = settings_store.load()
        if not settings.admin_configured:
            return redirect(url_for("setup"))
        if is_authenticated():
            return redirect(url_for("index"))

        error = ""
        if request.method == "POST":
            supplied = request.form.get("csrf_token", "")
            expected = session.get("csrf_token", "")
            if not (
                isinstance(expected, str)
                and secrets.compare_digest(expected, supplied)
            ):
                return Response("CSRF validation failed.", status=403)

            password = request.form.get("password", "")
            if settings_store.verify_admin_password(password):
                session.clear()
                session.permanent = True
                session["authenticated"] = True
                session["csrf_token"] = secrets.token_urlsafe(32)
                return redirect(url_for("index"))

            # A small fixed delay makes rapid guessing less attractive without
            # revealing whether the account exists or which check failed.
            time.sleep(0.75)
            error = "The password was not accepted."

        return render_template("login.html", error=error)

    @app.post("/logout")
    @login_required
    @csrf_required
    def logout() -> Response:
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @login_required
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/status")
    @login_required
    def status() -> Response:
        settings = settings_store.load()
        with sqlite.DB.init(configuration.db_path) as database:
            snapshots = database.get_recent_snapshots(hours=24, limit=96)
            payload = {
                "latest": (
                    _serialise_snapshots([snapshots[-1]])[0]
                    if snapshots
                    else None
                ),
                "history": _serialise_snapshots(snapshots),
                "devices": database.get_latest_devices(),
                "reports": database.get_recent_reports(limit=20),
                "chat": database.get_chat_messages(limit=50),
                "ai_enabled": settings.ai_enabled and settings.ai_key_active,
            }
        return jsonify(payload)

    @app.get("/api/ai-settings")
    @login_required
    def ai_settings_status() -> Response:
        settings = settings_store.load()
        # The saved key itself is intentionally absent. The browser receives
        # only the minimum metadata needed to render the settings panel.
        return jsonify(
            {
                "provider": "Groq",
                "model": settings.ai_model,
                "base_url": settings.ai_base_url,
                "key_active": settings.ai_key_active,
                "enabled": settings.ai_enabled and settings.ai_key_active,
                "last_test_ok": settings.ai_last_test_ok,
                "last_test_at": settings.ai_last_test_at or None,
                "last_error": settings.ai_last_error or None,
            }
        )

    @app.post("/api/ai-settings/key")
    @login_required
    @csrf_required
    def save_ai_key() -> Response:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "Expected a JSON object."}), 400

        api_key = body.get("api_key")
        if not isinstance(api_key, str):
            return jsonify({"error": "api_key must be a string."}), 400

        api_key = api_key.strip()
        if len(api_key) < 10 or len(api_key) > 512:
            return jsonify({"error": "The API key length is not valid."}), 400

        try:
            confirmation = _test_groq_key(
                api_key=api_key,
                model=secure_settings.DEFAULT_GROQ_MODEL,
                base_url=secure_settings.DEFAULT_GROQ_BASE_URL,
                request_timeout=configuration.request_timeout,
            )
        except Exception as exc:
            error = _safe_ai_error(exc)
            log.warning("Groq API-key validation failed: %s", error)
            return jsonify({"error": f"Groq rejected the connection test: {error}"}), 400

        settings_store.save_verified_ai_key(
            api_key=api_key,
            model=secure_settings.DEFAULT_GROQ_MODEL,
            base_url=secure_settings.DEFAULT_GROQ_BASE_URL,
        )
        return jsonify(
            {
                "saved": True,
                "key_active": True,
                "enabled": False,
                "confirmation": confirmation,
            }
        )

    @app.post("/api/ai-settings/test")
    @login_required
    @csrf_required
    def test_saved_ai_key() -> Response:
        settings = settings_store.load()
        if not settings.ai_api_key:
            return jsonify({"error": "No API key is stored."}), 409

        try:
            confirmation = _test_groq_key(
                api_key=settings.ai_api_key,
                model=settings.ai_model,
                base_url=settings.ai_base_url,
                request_timeout=configuration.request_timeout,
            )
        except Exception as exc:
            error = _safe_ai_error(exc)
            settings_store.record_ai_test(ok=False, error=error)
            log.warning("Saved Groq API-key test failed: %s", error)
            return jsonify({"error": f"Connection test failed: {error}"}), 400

        settings_store.record_ai_test(ok=True)
        return jsonify({"ok": True, "confirmation": confirmation})

    @app.post("/api/ai-settings/enabled")
    @login_required
    @csrf_required
    def set_ai_enabled() -> Response:
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
            return jsonify({"error": "enabled must be a JSON boolean."}), 400

        try:
            settings = settings_store.set_ai_enabled(body["enabled"])
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 409

        return jsonify({"enabled": settings.ai_enabled})

    @app.delete("/api/ai-settings/key")
    @login_required
    @csrf_required
    def remove_ai_key() -> Response:
        settings_store.remove_ai_key()
        return jsonify({"removed": True, "enabled": False})

    @app.get("/graph.png")
    @login_required
    def graph() -> Response:
        graph_path = Path(configuration.graph_path)
        if not graph_path.is_file():
            return Response("Graph not available yet.", status=404)

        response = send_file(
            graph_path,
            mimetype="image/png",
            conditional=True,
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/run-now")
    @login_required
    @csrf_required
    def run_now() -> Response:
        flag = Path(configuration.run_now_flag)
        flag.parent.mkdir(parents=True, exist_ok=True)

        # Replace is atomic on one filesystem. The collector either sees a
        # complete flag or no flag; it never observes a partly written file.
        temporary = flag.with_suffix(".tmp")
        temporary.write_text("requested by authenticated dashboard\n", encoding="utf-8")
        temporary.replace(flag)
        return jsonify({"accepted": True}), 202

    @app.post("/api/chat")
    @login_required
    @csrf_required
    def chat() -> Response:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "Expected a JSON object."}), 400

        message = body.get("message")
        if not isinstance(message, str):
            return jsonify({"error": "message must be a string."}), 400

        message = message.strip()
        if not message:
            return jsonify({"error": "message cannot be empty."}), 400
        if len(message) > 500:
            return jsonify({"error": "message must be 500 characters or fewer."}), 400

        settings = settings_store.load()
        with sqlite.DB.init(configuration.db_path) as database:
            database.add_chat_message(role="user", body=message)
            snapshots = database.get_recent_snapshots(hours=24, limit=96)
            devices = database.get_latest_devices()
            answer, matched = reporting.answer_local_question(
                message,
                snapshots=snapshots,
                latest_devices=devices,
            )

            ai_used = False
            if not matched and settings.ai_enabled and settings.ai_key_active:
                try:
                    with ai.Client.init(
                        settings.ai_api_key,
                        settings.ai_model,
                        settings.ai_base_url,
                        configuration.request_timeout,
                    ) as client:
                        ai_input = (
                            f"{reporting.build_ai_context(snapshots)}\n\n"
                            f"Question: {message}"
                        )
                        answer = client.send_message(
                            ai_input,
                            AI_CHAT_SYSTEM_PROMPT,
                        )
                        ai_used = True
                except Exception as exc:
                    log.exception("Optional Groq chat request failed.")
                    answer = (
                        f"{answer}\n\n"
                        f"Remote AI was enabled but unavailable: {_safe_ai_error(exc)}"
                    )

            database.add_chat_message(role="assistant", body=answer)

        return jsonify({"answer": answer, "ai_used": ai_used})

    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    conf = cfg.Config.init()
    app = create_app(conf)
    log.info("Starting authenticated local dashboard on %s:%d", conf.web_host, conf.web_port)
    serve(
        app,
        host=conf.web_host,
        port=conf.web_port,
        threads=4,
        ident="netmon-local",
    )


if __name__ == "__main__":
    main()
