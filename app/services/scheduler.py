from typing import Dict, List, Any, Optional
from ortools.sat.python import cp_model
import random


def generate_or_validate_schedule(request: Any, is_validation: bool = False) -> Dict:
    """
    Core logic for AI scheduling system.
    - is_validation = True: validate manually edited schedule from UI.
    - use_rules = False: Random Draft mode (ignore constraints).
    - use_rules = True: Constraint-based optimization mode.
    """
    model = cp_model.CpModel()

    # --- 1. INITIAL CONFIG & DATA NORMALIZATION ---
    shifts = ["M", "E", "N"]
    days = list(range(request.num_days))
    min_staff = request.min_staff or {"M": 2, "E": 2, "N": 1}

    # Ensure employees is a safe list of objects
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
        "violation": 10000,   # critical violations
        "senior": 5000,       # missing senior at night shift
        "workload": 3000,     # overworking
        "min_staff": 1000,    # staffing shortage
    }

    penalties = []
    violation_msgs = []

    # --- 4. HARD CONSTRAINTS ---

    # A. Rule Builder constraints (UI settings)
    use_rules = getattr(request, 'use_constraints', True)
    if use_rules and hasattr(request, 'constraints') and request.constraints:
        cons = request.constraints

        for f in getattr(cons, 'fixed_assignments', []):
            if (f.employee_id, f.day, f.shift) in x:
                model.Add(x[(f.employee_id, f.day, f.shift)] == 1)

        for off in getattr(cons, 'days_off', []):
            if (off.employee_id, off.day, off.shift) in x:
                model.Add(x[(off.employee_id, off.day, off.shift)] == 0)

    # B. Manual drag-and-drop schedule validation
    if is_validation and hasattr(request, 'manual_schedule') and request.manual_schedule:
        for d_str, day_data in request.manual_schedule.items():
            d_idx = int(d_str)
            for s in shifts:
                shift_employees = day_data.get(s, [])

                assigned_ids = [
                    e.get('id') if isinstance(e, dict) else getattr(e, 'id')
                    for e in shift_employees
                ]

                for emp in raw_employees:
                    eid = get_attr(emp, 'id')

                    if eid in assigned_ids:
                        model.Add(x[(eid, d_idx, s)] == 1)
                    else:
                        model.Add(x[(eid, d_idx, s)] == 0)

    # --- 5. BUSINESS RULES (HEALTHCARE LOGIC) ---
    for emp in raw_employees:
        eid = get_attr(emp, 'id')
        ename = get_attr(emp, 'name', "Unknown")
        is_senior = get_attr(emp, 'is_senior', False)

        for d in days:
            # 1. No double shift per day
            daily_total = sum(x[(eid, d, s)] for s in shifts)
            v = model.NewBoolVar(f"v_daily_{eid}_{d}")

            model.Add(daily_total <= 1).OnlyEnforceIf(v.Not())
            model.Add(daily_total > 1).OnlyEnforceIf(v)

            penalties.append(v * WEIGHTS["violation"])

            if is_validation:
                violation_msgs.append((v, f"{ename}: works 2 shifts on day {d+1}"))

        # 2. Rest constraint: Night → Morning forbidden
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

        # 3. Max 5 shifts per week (~40 hours)
        total_worked = sum(x[(eid, d, s)] for d in days for s in shifts)
        v_overwork = model.NewBoolVar(f"v_max_{eid}")

        model.Add(total_worked <= 5).OnlyEnforceIf(v_overwork.Not())
        model.Add(total_worked > 5).OnlyEnforceIf(v_overwork)

        penalties.append(v_overwork * WEIGHTS["workload"])

        if is_validation:
            violation_msgs.append((v_overwork, f"{ename}: exceeds 40 hours per week"))

    # 4. Minimum staffing requirement per shift
    missing_staff_vars = {}

    for d in days:
        for s in shifts:
            assigned = sum(x[(get_attr(e, 'id'), d, s)] for e in raw_employees)
            needed = min_staff.get(s, 1)

            slack = model.NewIntVar(0, 10, f"slack_{d}_{s}")
            model.Add(assigned + slack >= needed)

            penalties.append(slack * WEIGHTS["min_staff"])
            missing_staff_vars[(d, s)] = slack

    # 5. At least one senior at night shift
    for d in days:
        seniors_on_night = sum(
            x[(get_attr(e, 'id'), d, "N")]
            for e in raw_employees
            if get_attr(e, 'is_senior', False)
        )

        v_senior = model.NewBoolVar(f"v_senior_{d}")

        model.Add(seniors_on_night >= 1).OnlyEnforceIf(v_senior.Not())
        model.Add(seniors_on_night == 0).OnlyEnforceIf(v_senior)

        penalties.append(v_senior * WEIGHTS["senior"])

        if is_validation:
            violation_msgs.append((v_senior, f"Day {d+1}: Missing senior staff on night shift"))

    # Randomness for draft mode
    if not is_validation:
        for var in x.values():
            penalties.append(var * random.randint(0, 5))

    # --- 6. SOLVER ---
    model.Minimize(sum(penalties))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 8.0 if not is_validation else 3.0

    status = solver.Solve(model)

    # --- 7. OUTPUT ---
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        messages = []

        for v, msg in violation_msgs:
            if solver.Value(v):
                messages.append(msg)

        for (d, s), slack in missing_staff_vars.items():
            if solver.Value(slack) > 0:
                messages.append(f"Day {d+1}, Shift {s}: shortage {solver.Value(slack)} staff")

        if is_validation:
            result_schedule = request.manual_schedule
        else:
            result_schedule = {str(d): {s: [] for s in shifts} for d in days}

            for (eid, d, s), var in x.items():
                if solver.Value(var):
                    emp = next(e for e in raw_employees if get_attr(e, 'id') == eid)

                    result_schedule[str(d)][s].append({
                        "id": eid,
                        "name": get_attr(emp, 'name'),
                        "role": get_attr(emp, 'role'),
                        "is_senior": get_attr(emp, 'is_senior', False)
                    })

        return {
            "status": "success",
            "schedule": result_schedule,
            "statistics": {"shortage_details": list(set(messages))},
            "total_cost_score": float(solver.ObjectiveValue()),
            "message": "Optimization completed"
        }

    return {
        "status": "error",
        "message": "No feasible solution found under current constraints.",
        "total_cost_score": 0.0,
        "schedule": None,
        "statistics": {"shortage_details": ["Solver failed to find a valid solution"]}
    }


def generate_schedule(request: Any) -> Dict:
    """Wrapper for legacy API compatibility"""
    return generate_or_validate_schedule(request, is_validation=False)