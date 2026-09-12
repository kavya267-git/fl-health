# run.py
import uvicorn

if __name__ == "__main__":
    print("=" * 60)
    print("FL-HEALTH SERVER")
    print("Data stays local. Only learning travels.")
    print("=" * 60)
    print("Running at: http://localhost:8000")
    print("Docs:       http://localhost:8000/docs")
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)