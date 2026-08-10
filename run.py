from app import create_app
from app.scheduler import init_scheduler

app = create_app()
init_scheduler(app)

if __name__ == "__main__":
    # host=0.0.0.0 so it's reachable if you deploy this on a server/VM
    app.run(host="0.0.0.0", port=5000, debug=False)
