"""
Flask application factory.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask
from flask_cors import CORS


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = "iuo-secret-key-2024"
    CORS(app)

    from web.routes import bp
    app.register_blueprint(bp)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)
