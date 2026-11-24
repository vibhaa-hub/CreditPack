"""python -m workbench [--host 127.0.0.1] [--port 8000] [--model mistral/mistral-large-latest]"""
import argparse
import os

from dotenv import load_dotenv


def main():
    load_dotenv(".env")
    ap = argparse.ArgumentParser(prog="python -m workbench")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--model")
    a = ap.parse_args()
    if a.model:
        os.environ["CPA_MODEL"] = a.model
    import uvicorn
    from .app import create_app
    uvicorn.run(create_app(), host=a.host, port=a.port)


if __name__ == "__main__":
    main()
