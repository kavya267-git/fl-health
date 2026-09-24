# run.py
import sys
import os
import uvicorn

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

if __name__ == "__main__":
    print("=" * 60)
    print("FL-HEALTH SERVER")
    print("Data stays local. Only learning travels.")
    print("=" * 60)
    print("Running at: http://localhost:8000")
    print("Docs:       http://localhost:8000/docs")
    print("=" * 60)
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)