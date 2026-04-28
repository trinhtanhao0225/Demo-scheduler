from typing import Dict, List, Any
from ortools.sat.python import cp_model
import random


def generate_or_validate_schedule(request: Any, is_validation: bool = False) -> Dict:
    """
    Core logic for AI scheduling system.
    - is_validation = True: validate manually edited schedule + báo chi tiết vi phạm.
    """
    model = cp_model.CpModel()

    # --- 1. INITIAL CONFIG ---
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
        "violation": 10000,
        "senior": 5000,
        "workload": 3000,
        "min_staff": 1000,
    }

    penalties = []
    violation_msgs = []        # Dùng để thu thập violation khi validate

    # --- 4. HARD CONSTRAINTS ---

    # A. Rule Builder constraints
    use_rules = getattr(request, 'use_constraints', True)
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

    # B. Manual schedule validation
    if is_validation and hasattr(request, 'manual_schedule') and request.manual_schedule:
        for d_str, day_data in request.manual_schedule.items():
            d_idx = int(d_str)
            for s in shifts:
                shift_employees = day_data.get(s, [])
                assigned_ids = {
                    e.get('id') if isinstance(e, dict) else get_attr(e, 'id')
                    for e in shift_employees
                }

                for emp in raw_employees:
                    eid = get_attr(emp, 'id')
                    model.Add(x[(eid, d_idx, s)] == (1 if eid in assigned_ids else 0))

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

            penalties.append(v * WEIGHTS["violation"])

            if is_validation:
                violation_msgs.append((v, f"{ename}: works 2 shifts on day {d+1}"))

        # 2. Night → Morning forbidden
        for d in range(len(days) - 1):
            nm_transition = x[(eid, d, "N")] + x[(eid, d + 1, "M")]
            v = model.NewBoolVar(f"v_nm_{eid}_{d}")

            model.Add(nm_transition <= 1).OnlyEnforceIf(v.Not())
            model.Add(nm_transition > 1).OnlyEnforceIf(v)

            penalties.append(v * WEIGHTS["violation"])

            if is_validation:
                violation_msgs.append(
                    (v, f"{ename}: Night shift followed by Morning shift (Day {d+1}-{d+2})")
                )

        # 3. Max 5 shifts per week
        total_worked = sum(x[(eid, d, s)] for d in days for s in shifts)
        v_overwork = model.NewBoolVar(f"v_max_{eid}")

        model.Add(total_worked <= 5).OnlyEnforceIf(v_overwork.Not())
        model.Add(total_worked > 5).OnlyEnforceIf(v_overwork)

        penalties.append(v_overwork * WEIGHTS["workload"])

        if is_validation:
            violation_msgs.append((v_overwork, f"{ename}: exceeds 40 hours per week"))

    # 4. Minimum staffing
    missing_staff_vars = {}
    for d in days:
        for s in shifts:
            assigned = sum(x[(get_attr(e, 'id'), d, s)] for e in raw_employees)
            needed = min_staff.get(s, 1)

            slack = model.NewIntVar(0, 10, f"slack_{d}_{s}")
            model.Add(assigned + slack >= needed)

            penalties.append(slack * WEIGHTS["min_staff"])
            missing_staff_vars[(d, s)] = slack

    # 5. Senior on Night shift
    for d in days:
        seniors_on_night = sum(
            x[(get_attr(e, 'id'), d, "N")]
            for e in raw_employees if get_attr(e, 'is_senior', False)
        )

        v_senior = model.NewBoolVar(f"v_senior_{d}")

        model.Add(seniors_on_night >= 1).OnlyEnforceIf(v_senior.Not())
        model.Add(seniors_on_night == 0).OnlyEnforceIf(v_senior)

        penalties.append(v_senior * WEIGHTS["senior"])

        if is_validation:
            violation_msgs.append((v_senior, f"Day {d+1}: Missing senior staff on night shift"))

    # Randomness only in draft mode
    if not is_validation:
        for var in x.values():
            penalties.append(var * random.randint(0, 5))

    # --- 6. SOLVER ---
    model.Minimize(sum(penalties))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 8.0 if not is_validation else 3.0

    status = solver.Solve(model)

    # --- 7. OUTPUT (Giữ nguyên format cũ để không ảnh hưởng Frontend) ---
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        messages = []

        # Thu thập violation messages
        for v, msg in violation_msgs:
            if solver.Value(v):
                messages.append(msg)

        # Thu thập shortage
        for (d, s), slack in missing_staff_vars.items():
            if solver.Value(slack) > 0:
                messages.append(f"Day {d+1}, Shift {s}: shortage {solver.Value(slack)} staff")

        if is_validation:
            result_schedule = request.manual_schedule
        else:
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

        response = {
            "status": "success",
            "schedule": result_schedule,
            "statistics": {"shortage_details": list(set(messages))},
            "total_cost_score": float(solver.ObjectiveValue()),
            "message": "Optimization completed"
        }

        # ================== THÊM PHẦN NÀY ĐỂ VALIDATION TỐT HƠN ==================
        if is_validation:
            response["violations"] = [msg for msg in messages if "shortage" not in msg.lower()]
            response["shortages"] = [msg for msg in messages if "shortage" in msg.lower()]
            response["is_valid"] = len(response["violations"]) == 0 and len(response["shortages"]) == 0

        return response

    # Error case
    return {
        "status": "error",
        "message": "No feasible solution found under current constraints.",
        "total_cost_score": 0.0,
        "schedule": None,
        "statistics": {"shortage_details": ["Solver failed to find a valid solution"]},
        "violations": [] if not is_validation else ["Solver error"],
        "is_valid": False
    }


def generate_schedule(request: Any) -> Dict:
    """Wrapper for legacy API compatibility"""
    return generate_or_validate_schedule(request, is_validation=False)