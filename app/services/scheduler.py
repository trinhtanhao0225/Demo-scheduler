from typing import Dict, List, Any, Optional
from ortools.sat.python import cp_model
import random


def generate_or_validate_schedule(request: Any, is_validation: bool = False) -> Dict:
    """
    Core logic for AI scheduling system.
    - is_validation = True: validate manually edited schedule from UI + báo chi tiết vi phạm.
    """
    model = cp_model.CpModel()

    # --- 1. INITIAL CONFIG & DATA NORMALIZATION ---
    shifts = ["M", "E", "N"]
    days = list(range(request.num_days))
    min_staff = request.min_staff or {"M": 2, "E": 2, "N": 1}

    raw_employees = request.employees[:]
    if not is_validation:
        random.shuffle(raw_employees)

    def get_attr(obj, attr, default=None):
        return getattr(obj, attr, default)

    # --- 2. DECISION VARIABLES ---
    x = {}
    for emp in raw_employees:
        eid = get_attr(emp, 'id')
        for d in days:
            for s in shifts:
                x[(eid, d, s)] = model.NewBoolVar(f"x_{eid}_{d}_{s}")

    # --- 3. PENALTY WEIGHTS ---
    WEIGHTS = {
        "violation": 10000,   # critical violations (double shift, night→morning)
        "senior": 5000,
        "workload": 3000,
        "min_staff": 1000,
    }

    violations = []          # List of violation messages (for validation mode)
    penalty_terms = []

    # --- 4. HARD CONSTRAINTS (luôn áp dụng) ---

    use_rules = getattr(request, 'use_constraints', True)

    # A. Fixed assignments & Days off từ Rule Builder
    if use_rules and hasattr(request, 'constraints') and request.constraints:
        cons = request.constraints

        for f in getattr(cons, 'fixed_assignments', []):
            key = (f.employee_id, f.day, f.shift)
            if key in x:
                model.Add(x[key] == 1)

        for off in getattr(cons, 'days_off', []):
            key = (off.employee_id, off.day, off.shift)
            if key in x:
                model.Add(x[key] == 0)

    # B. Manual schedule validation (drag & drop từ UI)
    if is_validation and hasattr(request, 'manual_schedule') and request.manual_schedule:
        for d_str, day_data in request.manual_schedule.items():
            d = int(d_str)
            for s in shifts:
                shift_employees = day_data.get(s, [])
                assigned_ids = {
                    e.get('id') if isinstance(e, dict) else get_attr(e, 'id')
                    for e in shift_employees
                }

                for emp in raw_employees:
                    eid = get_attr(emp, 'id')
                    model.Add(x[(eid, d, s)] == (1 if eid in assigned_ids else 0))

    # --- 5. BUSINESS RULES ---

    for emp in raw_employees:
        eid = get_attr(emp, 'id')
        ename = get_attr(emp, 'name', "Unknown")
        is_senior = get_attr(emp, 'is_senior', False)

        # 1. No double shift per day
        for d in days:
            daily_total = sum(x[(eid, d, s)] for s in shifts)
            v = model.NewBoolVar(f"v_double_{eid}_{d}")

            model.Add(daily_total <= 1).OnlyEnforceIf(v.Not())
            model.Add(daily_total > 1).OnlyEnforceIf(v)

            penalty_terms.append(v * WEIGHTS["violation"])

            if is_validation:
                violations.append((v, f"{ename} làm 2 ca trong cùng 1 ngày (Ngày {d+1})"))

        # 2. Rest constraint: Night → Morning forbidden
        for d in range(len(days) - 1):
            nm = x[(eid, d, "N")] + x[(eid, d + 1, "M")]
            v = model.NewBoolVar(f"v_nm_{eid}_{d}")

            model.Add(nm <= 1).OnlyEnforceIf(v.Not())
            model.Add(nm > 1).OnlyEnforceIf(v)

            penalty_terms.append(v * WEIGHTS["violation"])

            if is_validation:
                violations.append((v, f"{ename}: Ca đêm (Ngày {d+1}) → Ca sáng (Ngày {d+2}) - Vi phạm nghỉ ngơi"))

        # 3. Max 5 shifts per week
        total_shifts = sum(x[(eid, d, s)] for d in days for s in shifts)
        v_over = model.NewBoolVar(f"v_over_{eid}")

        model.Add(total_shifts <= 5).OnlyEnforceIf(v_over.Not())
        model.Add(total_shifts > 5).OnlyEnforceIf(v_over)

        penalty_terms.append(v_over * WEIGHTS["workload"])

        if is_validation:
            violations.append((v_over, f"{ename}: Làm quá 5 ca/tuần (hiện tại {total_shifts})"))

    # 4. Minimum staffing
    missing_staff = {}
    for d in days:
        for s in shifts:
            assigned = sum(x[(get_attr(e, 'id'), d, s)] for e in raw_employees)
            needed = min_staff.get(s, 1)

            slack = model.NewIntVar(0, 20, f"slack_{d}_{s}")
            model.Add(assigned + slack >= needed)

            penalty_terms.append(slack * WEIGHTS["min_staff"])
            missing_staff[(d, s)] = slack

    # 5. Senior on Night shift
    for d in days:
        senior_night = sum(
            x[(get_attr(e, 'id'), d, "N")]
            for e in raw_employees if get_attr(e, 'is_senior', False)
        )
        v_senior = model.NewBoolVar(f"v_senior_{d}")

        model.Add(senior_night >= 1).OnlyEnforceIf(v_senior.Not())
        model.Add(senior_night == 0).OnlyEnforceIf(v_senior)

        penalty_terms.append(v_senior * WEIGHTS["senior"])

        if is_validation:
            violations.append((v_senior, f"Ngày {d+1}: Không có nhân viên senior ca đêm (N)"))

    # --- 6. Random noise (chỉ khi không validate) ---
    if not is_validation:
        for var in x.values():
            penalty_terms.append(var * random.randint(0, 5))

    # --- 7. OBJECTIVE ---
    model.Minimize(sum(penalty_terms))

    # --- 8. SOLVER ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 3.0 if is_validation else 8.0
    status = solver.Solve(model)

    # --- 9. RESULT ---
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "status": "error",
            "message": "Không tìm thấy giải pháp hợp lệ.",
            "schedule": None,
            "violations": ["Solver failed"],
            "total_cost_score": 0.0
        }

    # Thu thập các vi phạm thực tế
    actual_violations = []
    for v, msg in violations:
        if solver.Value(v) == 1:
            actual_violations.append(msg)

    # Shortage details
    shortage_details = []
    for (d, s), slack_var in missing_staff.items():
        slack = solver.Value(slack_var)
        if slack > 0:
            shortage_details.append(f"Ngày {d+1}, ca {s}: Thiếu {slack} người")

    if is_validation:
        result_schedule = request.manual_schedule
        message = "Đã kiểm tra lịch thủ công. " + ("Có vi phạm!" if actual_violations else "Lịch hợp lệ.")
    else:
        # Build schedule from solver (giữ nguyên logic cũ của bạn)
        result_schedule = {str(d): {s: [] for s in shifts} for d in days}
        for (eid, d, s), var in x.items():
            if solver.Value(var):
                emp = next((e for e in raw_employees if get_attr(e, 'id') == eid), None)
                if emp:
                    result_schedule[str(d)][s].append({
                        "id": eid,
                        "name": get_attr(emp, 'name'),
                        "role": get_attr(emp, 'role'),
                        "is_senior": get_attr(emp, 'is_senior', False)
                    })
        message = "Tạo lịch thành công"

    return {
        "status": "success",
        "schedule": result_schedule,
        "violations": actual_violations,                    # <-- Quan trọng nhất khi validate
        "shortage_details": shortage_details,
        "total_cost_score": float(solver.ObjectiveValue()),
        "message": message,
        "is_valid": len(actual_violations) == 0 and len(shortage_details) == 0
    }


def generate_schedule(request: Any) -> Dict:
    """Wrapper cho API cũ"""
    return generate_or_validate_schedule(request, is_validation=False)