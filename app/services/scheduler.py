from typing import Dict, List, Any
from ortools.sat.python import cp_model
import random

def generate_or_validate_schedule(request: Any, is_validation: bool = False) -> Dict:
    """
    Hệ thống tạo và kiểm tra lịch trực thông minh.
    - is_validation = True: Kiểm tra lịch thủ công từ UI gửi lên.
    - request.use_constraints = False: Chế độ Random Draft thuần túy (Bỏ qua Xanh/Đỏ).
    """
    model = cp_model.CpModel()

    # --- Basic Configuration ---
    shifts = ["M", "E", "N"]
    days = list(range(request.num_days))
    min_staff = request.min_staff or {"M": 2, "E": 2, "N": 1}
    employees = request.employees[:]
    
    # Shuffle để kết quả mỗi lần Random Draft khác nhau hoàn toàn
    if not is_validation:
        random.shuffle(employees)

    # Kiểm tra xem có dùng Constraints (Xanh/Đỏ) không
    # Mặc định là True trừ khi Frontend gửi False (dành cho Random Draft)
    use_rules = getattr(request, 'use_constraints', True)

    # ================= 1. DECISION VARIABLES =================
    x = {}
    for emp in employees:
        for d in days:
            for s in shifts:
                x[(emp.id, d, s)] = model.NewBoolVar(f"x_{emp.id}_{d}_{s}")

    # ================= 2. PENALTY WEIGHTS =================
    WEIGHTS = {
        "violation": 5000,   # Lỗi cực nặng (N->M)
        "workload": 2000,    # Quá 40h
        "senior": 3000,      # Thiếu Senior
        "min_staff": 500,    # Thiếu người
    }

    penalties = []
    violation_msgs = []

    # ================= 3. HARD CONSTRAINTS & RULES =================
    
    # --- PHẦN A: Chỉ áp dụng Tab Constraints (Xanh/Đỏ) nếu use_rules=True ---
    if use_rules and hasattr(request, 'constraints') and request.constraints:
        cons = request.constraints
        # Ép làm (Fixed - Xanh)
        for f in cons.fixed_assignments:
            if (f.employee_id, f.day, f.shift) in x:
                model.Add(x[(f.employee_id, f.day, f.shift)] == 1)
        # Ép nghỉ (Off - Đỏ)
        for off in cons.days_off:
            if (off.employee_id, off.day, off.shift) in x:
                model.Add(x[(off.employee_id, off.day, off.shift)] == 0)

    # --- PHẦN B: Khóa theo lịch hiện tại (Chỉ khi nhấn Validate/Sync) ---
    if is_validation and hasattr(request, 'manual_schedule') and request.manual_schedule:
        for d_str, day_data in request.manual_schedule.items():
            d_idx = int(d_str)
            for s in shifts:
                shift_employees = day_data.get(s, [])
                assigned_ids = [e.get('id') if isinstance(e, dict) else e.id for e in shift_employees]
                for emp in employees:
                    if emp.id in assigned_ids:
                        model.Add(x[(emp.id, d_idx, s)] == 1)
                    else:
                        model.Add(x[(emp.id, d_idx, s)] == 0)

    # ================= 4. BUSINESS LOGIC (SOFT CONSTRAINTS) =================
    for emp in employees:
        # 1. Tối đa 1 ca/ngày
        for d in days:
            daily_total = sum(x[(emp.id, d, s)] for s in shifts)
            v = model.NewBoolVar(f"v_daily_{emp.id}_{d}")
            model.Add(daily_total <= 1).OnlyEnforceIf(v.Not())
            model.Add(daily_total > 1).OnlyEnforceIf(v)
            penalties.append(v * WEIGHTS["violation"])
            if is_validation:
                violation_msgs.append((v, f"{emp.name}: Multiple shifts on Day {d+1}"))

        # 2. Nghỉ giữa ca (N -> M)
        for d in range(len(days) - 1):
            nm_transition = x[(emp.id, d, "N")] + x[(emp.id, d + 1, "M")]
            v = model.NewBoolVar(f"v_nm_{emp.id}_{d}")
            model.Add(nm_transition <= 1).OnlyEnforceIf(v.Not())
            model.Add(nm_transition > 1).OnlyEnforceIf(v)
            penalties.append(v * WEIGHTS["violation"])
            if is_validation:
                violation_msgs.append((v, f"{emp.name}: Night shift followed by Morning (Day {d+1}-{d+2})"))

        # 3. Định mức 40h (Max 5 ca/tuần)
        total_worked = sum(x[(emp.id, d, s)] for d in days for s in shifts)
        v_overwork = model.NewBoolVar(f"v_max_{emp.id}")
        model.Add(total_worked <= 5).OnlyEnforceIf(v_overwork.Not())
        model.Add(total_worked > 5).OnlyEnforceIf(v_overwork)
        penalties.append(v_overwork * WEIGHTS["workload"])
        violation_msgs.append((v_overwork, f"{emp.name}: Over 40h workload"))

    # 4. Thiếu người (Slack variables)
    missing_staff_vars = {}
    for d in days:
        for s in shifts:
            assigned = sum(x[(emp.id, d, s)] for emp in employees)
            needed = min_staff.get(s, 1)
            slack = model.NewIntVar(0, 10, f"slack_{d}_{s}")
            model.Add(assigned + slack >= needed)
            penalties.append(slack * WEIGHTS["min_staff"])
            missing_staff_vars[(d, s)] = slack

    # 5. Senior trực đêm
    for d in days:
        seniors_on_night = sum(x[(emp.id, d, "N")] for emp in employees if emp.is_senior)
        v_senior = model.NewBoolVar(f"v_senior_{d}")
        model.Add(seniors_on_night >= 1).OnlyEnforceIf(v_senior.Not())
        model.Add(seniors_on_night == 0).OnlyEnforceIf(v_senior)
        penalties.append(v_senior * WEIGHTS["senior"])
        violation_msgs.append((v_senior, f"Day {d+1}: Night shift lacks Senior staff"))

    # Nhiễu Random
    for var in x.values():
        penalties.append(var * random.randint(0, 2))

    # ================= 5. SOLVER CONFIG =================
    model.Minimize(sum(penalties))
    solver = cp_model.CpSolver()
    # Random Draft cần nhiều thời gian tìm kiếm hơn một chút
    solver.parameters.max_time_in_seconds = 8.0 if not is_validation else 3.0
    
    status = solver.Solve(model)

    # ================= 6. OUTPUT =================
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        messages = []
        for v, msg in violation_msgs:
            if solver.Value(v): messages.append(msg)
        for (d, s), slack in missing_staff_vars.items():
            if solver.Value(slack) > 0:
                messages.append(f"Day {d+1}, Shift {s}: Missing {solver.Value(slack)} staff")

        if is_validation:
            result_schedule = request.manual_schedule
        else:
            result_schedule = {str(d): {s: [] for s in shifts} for d in days}
            for (eid, d, s), var in x.items():
                if solver.Value(var):
                    emp = next(e for e in employees if e.id == eid)
                    result_schedule[str(d)][s].append({
                        "id": emp.id, "name": emp.name, "role": emp.role, "is_senior": emp.is_senior
                    })

        return {
            "status": "success", "schedule": result_schedule,
            "statistics": {"shortage_details": list(set(messages))}
        }

    return {"status": "error", "message": "Infeasible: Request conflicts with Hard Rules."}