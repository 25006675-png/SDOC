#!/usr/bin/env python3
"""Run the SDOC backend locally."""
import uvicorn


if __name__ == "__main__":
    uvicorn.run("sdoc.api:app", host="127.0.0.1", port=8001, reload=False)
