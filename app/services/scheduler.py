from typing import Dict, List
from ortools.sat.python import cp_model
import random


def generate_or_validate_schedule(request, is_validation: bool = False) -> Dict:
    model = cp_model.CpModel()

    shifts = ["M", "E", "N"]
    days = list(range(request.num_days))
    min_staff = request.min_staff or {"M": 2, "E": 2, "N": 1}

    employees = request.employees[:]
    random.shuffle(employees)

    # ================= VARIABLES =================
    x = {}
    for emp in employees:
        for d in days:
            for s in shifts:
                x[(emp.id, d, s)] = model.NewBoolVar(f"x_{emp.id}_{d}_{s}")

    # ================= WEIGHTS =================
    WEIGHTS = {
        "fixed": 10000,
        "day_off": 10000,
        "violation": 3000,
        "min_staff": 100,
        "workload": 2000,
        "senior": 3000
    }

    penalties = []

    # ================= VALIDATION =================
    if is_validation and request.manual_schedule:
        for d_str, day_data in request.manual_schedule.items():
            d_idx = int(d_str)
            for s in shifts:
                shift_employees = day_data.get(s, []) if isinstance(day_data, dict) else getattr(day_data, s, [])
                assigned_ids = [e.id if hasattr(e, 'id') else e.get('id') for e in shift_employees]

                for emp in employees:
                    if emp.id in assigned_ids:
                        model.Add(x[(emp.id, d_idx, s)] == 1)
                    else:
                        model.Add(x[(emp.id, d_idx, s)] == 0)

    # ================= CONSTRAINTS =================
    if not is_validation and request.constraints:
        cons = request.constraints

        for f in cons.fixed_assignments:
            eid, d, s = f.employee_id, f.day, f.shift
            if (eid, d, s) in x:
                v = model.NewBoolVar(f"viol_fixed_{eid}_{d}_{s}")
                model.Add(x[(eid, d, s)] == 1).OnlyEnforceIf(v.Not())
                model.Add(x[(eid, d, s)] == 0).OnlyEnforceIf(v)
                penalties.append(v * WEIGHTS["fixed"])

        for off in cons.days_off:
            eid, d, s = off.employee_id, off.day, off.shift
            if (eid, d, s) in x:
                v = model.NewBoolVar(f"viol_off_{eid}_{d}_{s}")
                model.Add(x[(eid, d, s)] == 0).OnlyEnforceIf(v.Not())
                model.Add(x[(eid, d, s)] == 1).OnlyEnforceIf(v)
                penalties.append(v * WEIGHTS["day_off"])

    # ================= LOGIC =================
    violation_msgs = []

    for emp in employees:
        # 1 shift per day
        for d in days:
            total = sum(x[(emp.id, d, s)] for s in shifts)
            v = model.NewBoolVar(f"v_daily_{emp.id}_{d}")
            model.Add(total <= 1).OnlyEnforceIf(v.Not())
            model.Add(total > 1).OnlyEnforceIf(v)
            penalties.append(v * WEIGHTS["violation"])

        # N -> M rule
        for d in range(len(days) - 1):
            nm = x[(emp.id, d, "N")] + x[(emp.id, d + 1, "M")]
            v = model.NewBoolVar(f"v_nm_{emp.id}_{d}")
            model.Add(nm <= 1).OnlyEnforceIf(v.Not())
            model.Add(nm > 1).OnlyEnforceIf(v)
            penalties.append(v * WEIGHTS["violation"])

        # MAX 40h (5 shifts)
        MAX_SHIFTS = 5
        total_shifts = sum(x[(emp.id, d, s)] for d in days for s in shifts)

        v = model.NewBoolVar(f"v_max_{emp.id}")
        model.Add(total_shifts <= MAX_SHIFTS).OnlyEnforceIf(v.Not())
        model.Add(total_shifts > MAX_SHIFTS).OnlyEnforceIf(v)

        penalties.append(v * WEIGHTS["workload"])
        violation_msgs.append((v, f"{emp.name}: exceeds 40 working hours"))

    # ================= MIN STAFF =================
    missing = {}

    for d in days:
        for s in shifts:
            missing[(d, s)] = model.NewIntVar(0, 10, f"miss_{d}_{s}")
            assigned = sum(x[(emp.id, d, s)] for emp in employees)
            model.Add(assigned + missing[(d, s)] >= min_staff.get(s, 1))
            penalties.append(missing[(d, s)] * WEIGHTS["min_staff"])

    # ================= SENIOR NIGHT =================
    for d in days:
        senior_night = sum(
            x[(emp.id, d, "N")] for emp in employees if emp.is_senior
        )

        v = model.NewBoolVar(f"v_senior_night_{d}")
        model.Add(senior_night >= 1).OnlyEnforceIf(v.Not())
        model.Add(senior_night == 0).OnlyEnforceIf(v)

        penalties.append(v * WEIGHTS["senior"])
        violation_msgs.append((v, f"Day {d+1}: missing senior on night shift"))

    # ================= RANDOM =================
    for var in x.values():
        penalties.append(var * random.randint(0, 2))

    # ================= OBJECTIVE =================
    model.Minimize(sum(penalties))

    # ================= SOLVER =================
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    solver.parameters.random_seed = random.randint(1, 100000)
    solver.parameters.num_search_workers = 8
    solver.parameters.randomize_search = True

    status = solver.Solve(model)

    # ================= RESULT =================
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        messages = []

        for v, msg in violation_msgs:
            if solver.Value(v):
                messages.append(msg)

        for (d, s), m in missing.items():
            if solver.Value(m) > 0:
                messages.append(f"Day {d+1}, shift {s}: missing {solver.Value(m)} staff")

        if is_validation:
            result_schedule = request.manual_schedule
        else:
            result_schedule = {str(d): {s: [] for s in shifts} for d in days}

            for (eid, d, s), var in x.items():
                if solver.Value(var):
                    emp = next(e for e in employees if e.id == eid)
                    result_schedule[str(d)][s].append({
                        "id": emp.id,
                        "name": emp.name,
                        "role": emp.role,
                        "is_senior": emp.is_senior
                    })

        return {
            "status": "success",
            "schedule": result_schedule,
            "statistics": {"shortage_details": messages},
            "total_cost_score": float(solver.ObjectiveValue()),
            "message": "Success"
        }

    return {
        "status": "error",
        "message": "No feasible schedule found."
    }


def generate_schedule(request) -> Dict:
    return generate_or_validate_schedule(request, is_validation=False)