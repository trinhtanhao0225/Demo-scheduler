from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import GenerateScheduleRequest, ScheduleResponse
from app.services.scheduler import generate_or_validate_schedule

app = FastAPI(title="AI Scheduling System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/generate-schedule", response_model=ScheduleResponse)
async def generate_schedule(req: GenerateScheduleRequest):
    try:
        # Tự động bật validation nếu có manual_schedule
        is_validation = bool(req.manual_schedule and len(req.manual_schedule) > 0)

        result = generate_or_validate_schedule(req, is_validation=is_validation)

        return ScheduleResponse(**result)
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health():
    return {"status": "ok"}