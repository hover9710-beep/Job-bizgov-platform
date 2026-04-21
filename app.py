"""Flask 서버 진입점 — `python app.py` 로 실행."""
from appy import app

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
