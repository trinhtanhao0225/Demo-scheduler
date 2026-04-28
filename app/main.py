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
        # --- 1. KIỂM TRA TRẠNG THÁI TỪ REQUEST ---
        
        # Có lịch kéo thả gửi lên không?
        has_manual = bool(req.manual_schedule and len(req.manual_schedule) > 0)
        
        # Có yêu cầu dùng luật Xanh/Đỏ không?
        use_rules = getattr(req, 'use_constraints', True)

        # --- 2. ĐIỀU HƯỚNG LOGIC ---

        if has_manual:
            # CHỨC NĂNG: VALIDATE & SYNC
            # Ép AI kiểm tra lịch hiện tại + các ràng buộc
            result = generate_or_validate_schedule(req, is_validation=True)
            
        elif not use_rules:
            # CHỨC NĂNG: RANDOM DRAFT
            # AI tự làm mới hoàn toàn, bỏ qua các ô Xanh/Đỏ
            result = generate_or_validate_schedule(req, is_validation=False)
            
        else:
            # CHỨC NĂNG: APPLY CONSTRAINTS
            # AI tự xếp lịch nhưng phải né ô Đỏ, giữ ô Xanh
            result = generate_or_validate_schedule(req, is_validation=False)

        # Trả kết quả về cho React
        return ScheduleResponse(**result)

    except Exception as e:
        import traceback
        print("--- SERVER ERROR LOG ---")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/")
def root():
    return {"message": "API is running"}