from typing import Dict, Optional, List
from ortools.sat.python import cp_model

def generate_or_validate_schedule(request, is_validation: bool = False) -> Dict:
    model = cp_model.CpModel()
    shifts = ["M", "E", "N"]
    days = list(range(request.num_days))
    min_staff = request.min_staff or {"M": 2, "E": 2, "N": 1}
    shift_hours = {"M": 8, "E": 8, "N": 10}   # Hours per shift

    # ================= VARIABLES =================
    x = {}
    for emp in request.employees:
        for d in days:
            for s in shifts:
                x[(emp.id, d, s)] = model.NewBoolVar(f"x_{emp.id}_{d}_{s}")

    violation_vars = []
    preference_violations = []  # To calculate preference penalties
    overtime_vars = []          # To calculate overtime penalties

    # ================= HARD CONSTRAINTS =================
    for emp in request.employees:
        # 1. Max 1 shift per day
        for d in days:
            daily_shifts = sum(x[(emp.id, d, s)] for s in shifts)
            if is_validation:
                v = model.NewBoolVar(f"v_daily_{emp.id}_{d}")
                model.Add(daily_shifts <= 1).OnlyEnforceIf(v.Not())
                model.Add(daily_shifts > 1).OnlyEnforceIf(v)
                violation_vars.append((v, f"{emp.name}: Working >1 shift on Day {d+1}"))
            else:
                model.Add(daily_shifts <= 1)

        # 2. No Night shift followed by Morning shift (Rest rule)
        for d in range(request.num_days - 1):
            transition = x[(emp.id, d, "N")] + x[(emp.id, d + 1, "M")]
            if is_validation:
                v = model.NewBoolVar(f"v_nm_{emp.id}_{d}")
                model.Add(transition <= 1).OnlyEnforceIf(v.Not())
                model.Add(transition > 1).OnlyEnforceIf(v)
                violation_vars.append((v, f"{emp.name}: Night shift on Day {d+1} followed by Morning on Day {d+2}"))
            else:
                model.Add(transition <= 1)

    # ================= STAFFING REQUIREMENTS =================
    missing_count = {(d, s): model.NewIntVar(0, 20, f"m_{d}_{s}") for d in days for s in shifts}
    missing_senior = {d: model.NewIntVar(0, 5, f"ms_{d}") for d in days}

    for d in days:
        for s in shifts:
            assigned = sum(x[(emp.id, d, s)] for emp in request.employees)
            model.Add(assigned + missing_count[(d, s)] >= min_staff.get(s, 2))

        # Night shift requires at least one Senior
        seniors_night = sum(x[(emp.id, d, "N")] for emp in request.employees if emp.is_senior)
        model.Add(seniors_night + missing_senior[d] >= 1)

    # ================= SOFT CONSTRAINTS =================

    # 3. Max Weekly Hours (weekly_max_hours)
    for emp in request.employees:
        total_hours = sum(x[(emp.id, d, s)] * shift_hours[s] for d in days for s in shifts)
        overtime = model.NewIntVar(0, 100, f"ot_{emp.id}")
        # overtime >= total_hours - limit
        model.Add(total_hours - emp.weekly_max_hours <= overtime)
        overtime_vars.append(overtime)

    # 4. Employee Preferences (preferred_shifts)
    for emp in request.employees:
        if not hasattr(emp, 'preferred_shifts') or not emp.preferred_shifts:
            continue
        for s, preferred_days in emp.preferred_shifts.items():
            if s not in shifts: continue
            for d in preferred_days:
                if d not in days: continue
                # Penalty if the employee is NOT assigned to their preferred shift
                pref_viol = model.NewBoolVar(f"pref_viol_{emp.id}_{d}_{s}")
                model.Add(x[(emp.id, d, s)] == 0).OnlyEnforceIf(pref_viol)
                model.Add(x[(emp.id, d, s)] == 1).OnlyEnforceIf(pref_viol.Not())
                preference_violations.append(pref_viol)

    # ================= FORCE MANUAL SCHEDULE (Validation Mode) =================
    if is_validation and request.manual_schedule:
        for d_str, day_data in request.manual_schedule.items():
            d = int(d_str)
            if d not in days: continue
            for s, assigned_list in day_data.items():
                if s not in shifts: continue
                assigned_ids = {a.id for a in assigned_list}
                for emp in request.employees:
                    model.Add(x[(emp.id, d, s)] == (1 if emp.id in assigned_ids else 0))

    # ================= OBJECTIVE (Minimize penalties) =================
    HARD_PENALTY = 100000
    SOFT_PENALTY = 5000

    obj = sum(missing_count[(d, s)] * HARD_PENALTY for d in days for s in shifts)
    obj += sum(missing_senior[d] * HARD_PENALTY * 3 for d in days)
    obj += sum(v * HARD_PENALTY * 5 for v, _ in violation_vars)
    obj += sum(ot * SOFT_PENALTY for ot in overtime_vars) 
    obj += sum(v * SOFT_PENALTY for v in preference_violations)

    model.Minimize(obj)

    # ================= SOLVER EXECUTION =================
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 15.0
    status = solver.Solve(model)

    messages = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # 1. Staffing shortage warnings
        for d in days:
            for s in shifts:
                miss = solver.Value(missing_count[(d, s)])
                if miss > 0:
                    messages.append(f"Day {d+1} ({s}): Shortage of {miss} staff")

            if solver.Value(missing_senior[d]) > 0:
                messages.append(f"Day {d+1}: No Senior assigned to Night shift ⭐")

        # 2. Hard constraint violation warnings (Validation only)
        for v, msg in violation_vars:
            if solver.Value(v) > 0:
                messages.append(msg)

        # 3. Overtime warnings
        for emp in request.employees:
            total_work = sum(solver.Value(x[(emp.id, d, s)]) * shift_hours[s] for d in days for s in shifts)
            ot_hours = total_work - emp.weekly_max_hours
            if ot_hours > 0:
                messages.append(f"{emp.name}: Overtime of {ot_hours}h (Max limit: {emp.weekly_max_hours}h/week)")

        # Build final schedule object
        res_schedule = {str(d): {s: [] for s in shifts} for d in days}
        for d in days:
            for s in shifts:
                for emp in request.employees:
                    if solver.Value(x[(emp.id, d, s)]) == 1:
                        res_schedule[str(d)][s].append({
                            "id": emp.id, "name": emp.name,
                            "role": emp.role, "is_senior": emp.is_senior
                        })

        return {
            "status": "success",
            "schedule": res_schedule,
            "statistics": {"shortage_details": messages},
            "total_cost_score": solver.ObjectiveValue(),
            "message": "Schedule generated successfully"
        }

    return {
        "status": "error",
        "message": "Solver could not find a feasible solution",
        "schedule": {},
        "statistics": {"shortage_details": ["Infeasible Solution"]},
        "total_cost_score": 0
    }