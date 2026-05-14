"""Flask application factory + entrypoint."""
from __future__ import annotations

import logging
import os

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from app import db
from app.scheduler import get_scheduler
from app.web import bp as web_bp

log = logging.getLogger(__name__)


def create_app() -> Flask:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    app = Flask(__name__)
    secret = os.environ.get("FLASK_SECRET")
    if not secret:
        raise RuntimeError(
            "FLASK_SECRET must be set (generate via "
            "`python -c 'import secrets; print(secrets.token_hex(32))'`)."
        )
    app.config["SECRET_KEY"] = secret
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_db()
    app.register_blueprint(web_bp)

    sched = get_scheduler()
    if not sched.sched.running:
        sched.start()

    log.info("hue-iss app ready.")
    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", "5057"))
    app.run(host="0.0.0.0", port=port, debug=False)
