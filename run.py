"""Start the Siron SQL Tracer web app:  python run.py"""
from siron_tracer import create_app
from siron_tracer.config import load_settings

if __name__ == "__main__":
    settings = load_settings()
    app = create_app(settings)
    print("Siron SQL Tracer: http://%s:%d" % (settings.host, settings.port))
    app.run(host=settings.host, port=settings.port, debug=False, threaded=True)
