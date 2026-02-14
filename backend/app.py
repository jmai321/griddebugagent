from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="GridDebugAgent API")

# Allow frontend to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------
#  Models
# ---------------------

class DiagnoseRequest(BaseModel):
    """Request body for the /diagnose endpoint."""
    test_case: str                          # selected test-case id
    pipeline: str = "baseline"              # "baseline" or "agentic"


class DiagnoseResult(BaseModel):
    """Response body returned by the /diagnose endpoint."""
    test_case: str
    pipeline: str
    report: str                             # text output shown in the UI


# ---------------------
#  GET  /testcases
# ---------------------

@app.get("/testcases")
def get_testcases():
    """
    Return the list of available test cases for the dropdown.
    TODO: populate with real scenario data.
    """
    return {
        "testcases": []
    }


# ---------------------
#  POST /diagnose
# ---------------------

@app.post("/diagnose", response_model=DiagnoseResult)
def run_diagnose(req: DiagnoseRequest):
    """
    Run the selected test case through the chosen pipeline
    (baseline or agentic) and return the diagnosis report.
    TODO: wire up baseline / agentic logic.
    """
    report = ""  # placeholder

    return DiagnoseResult(
        test_case=req.test_case,
        pipeline=req.pipeline,
        report=report,
    )


# ---------------------
#  GET  /result/{test_case}
# ---------------------

@app.get("/result/{test_case}")
def get_result(test_case: str):
    """
    Retrieve the latest diagnosis text output for a given test case.
    TODO: fetch stored result.
    """
    return {
        "test_case": test_case,
        "report": "",
    }


# ---------------------
#  Entrypoint
# ---------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
