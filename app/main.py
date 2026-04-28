from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.schemas import GenerateScheduleRequest, ScheduleResponse
from app.services.scheduler import generate_schedule, generate_or_validate_schedule

app = FastAPI(title="AI Scheduling System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/generate-schedule", response_model=ScheduleResponse)
async def generate_schedule_api(req: GenerateScheduleRequest):
    try:
        # Xác định loại request
        has_manual_schedule = bool(req.manual_schedule and len(req.manual_schedule) > 0)
        use_constraints = getattr(req, 'use_constraints', True)

        # ================== LOGIC ĐIỀU HƯỚNG RÕ RÀNG ==================
        if has_manual_schedule:
            # === MODE 1: VALIDATE lịch thủ công từ UI (kéo thả) ===
            result = generate_or_validate_schedule(req, is_validation=True)

        elif not use_constraints:
            # === MODE 2: RANDOM DRAFT (bỏ qua hết ràng buộc) ===
            # Lưu ý: Nếu muốn thật sự random hoàn toàn, có thể cần chỉnh scheduler sau
            result = generate_or_validate_schedule(req, is_validation=False)

        else:
            # === MODE 3: TẠO LỊCH THEO RÀNG BUỘC (Constraint-based) ===
            result = generate_or_validate_schedule(req, is_validation=False)

        # Trả về response (FastAPI sẽ tự validate với ScheduleResponse)
        return ScheduleResponse(**result)

    except Exception as e:
        import traceback
        print("--- SERVER ERROR LOG ---")
        print(traceback.format_exc())
        
        # Trả về lỗi chi tiết hơn cho developer
        raise HTTPException(
            status_code=500, 
            detail=f"Schedule generation failed: {str(e)}"
        )


@app.get("/")
async def root():
    return {
        "message": "AI Scheduling System API is running",
        "version": "1.0",
        "endpoints": {
            "generate_schedule": "/generate-schedule (POST)"
        }
    }