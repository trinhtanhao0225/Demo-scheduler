from typing import Dict, List, Any
from ortools.sat.python import cp_model
import random

def generate_or_validate_schedule(request: Any, is_validation: bool = False) -> Dict:
    """
    Generates or validates a staff schedule.
    Fixed Assignments and Days Off are treated as HARD constraints (highest priority).
    """
    model = cp_model.CpModel()

    # --- Basic Configuration ---
    shifts = ["M", "E", "N"]  # Morning, Evening, Night
    days = list(range(request.num_days))
    min_staff = request.min_staff or {"M": 2, "E": 2, "N": 1}

    # Shuffle employees to ensure variety in different runs
    employees = request.employees[:]
    random.shuffle(employees)

    # ================= 1. DECISION VARIABLES =================
    # x[(employee_id, day, shift)] = 1 if assigned, 0 otherwise
    x = {}
    for emp in employees:
        for d in days:
            for s in shifts:
                x[(emp.id, d, s)] = model.NewBoolVar(f"x_{emp.id}_{d}_{s}")

    # ================= 2. PENALTY WEIGHTS (SOFT CONSTRAINTS) =================
    # These are used for optimization when hard constraints are already met.
    WEIGHTS = {
        "violation": 5000,   # Rules like N->M or multiple shifts per day
        "workload": 2000,    # Exceeding 40h/week
        "senior": 3000,      # Missing a senior on night shift
        "min_staff": 500,    # Understaffing penalty
    }

    penalties = []
    violation_msgs = []

    # ================= 3. HARD CONSTRAINTS (TOP PRIORITY) =================
    
    # CASE A: Validation Mode
    # Force variables to match the provided manual schedule
    if is_validation and hasattr(request, 'manual_schedule'):
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

    # CASE B: Generation Mode
    # Strictly enforce Fixed Assignments and Days Off
    elif not is_validation and hasattr(request, 'constraints'):
        cons = request.constraints
        
        # MANDATORY WORKING DAYS (Fixed)
        for f in cons.fixed_assignments:
            if (f.employee_id, f.day, f.shift) in x:
                model.Add(x[(f.employee_id, f.day, f.shift)] == 1)

        # MANDATORY DAYS OFF
        for off in cons.days_off:
            if (off.employee_id, off.day, off.shift) in x:
                model.Add(x[(off.employee_id, off.day, off.shift)] == 0)

    # ================= 4. BUSINESS LOGIC & PENALTIES =================
    for emp in employees:
        # Constraint: Maximum 1 shift per day
        for d in days:
            daily_total = sum(x[(emp.id, d, s)] for s in shifts)
            v = model.NewBoolVar(f"v_daily_{emp.id}_{d}")
            model.Add(daily_total <= 1).OnlyEnforceIf(v.Not())
            model.Add(daily_total > 1).OnlyEnforceIf(v)
            penalties.append(v * WEIGHTS["violation"])

        # Rest Rule: No Night shift (N) followed by a Morning shift (M) the next day
        for d in range(len(days) - 1):
            nm_transition = x[(emp.id, d, "N")] + x[(emp.id, d + 1, "M")]
            v = model.NewBoolVar(f"v_nm_{emp.id}_{d}")
            model.Add(nm_transition <= 1).OnlyEnforceIf(v.Not())
            model.Add(nm_transition > 1).OnlyEnforceIf(v)
            penalties.append(v * WEIGHTS["violation"])

        # Workload: Max 5 shifts per period (e.g., 40 hours)
        MAX_SHIFTS = 5
        total_worked = sum(x[(emp.id, d, s)] for d in days for s in shifts)
        v_overwork = model.NewBoolVar(f"v_max_{emp.id}")
        model.Add(total_worked <= MAX_SHIFTS).OnlyEnforceIf(v_overwork.Not())
        model.Add(total_worked > MAX_SHIFTS).OnlyEnforceIf(v_overwork)
        penalties.append(v_overwork * WEIGHTS["workload"])
        violation_msgs.append((v_overwork, f"{emp.name}: Exceeds 40h workload"))

    # Min Staffing Levels
    missing_staff_vars = {}
    for d in days:
        for s in shifts:
            assigned = sum(x[(emp.id, d, s)] for emp in employees)
            needed = min_staff.get(s, 1)
            
            # Use a slack variable to represent the number of missing staff
            slack = model.NewIntVar(0, 10, f"slack_{d}_{s}")
            model.Add(assigned + slack >= needed)
            penalties.append(slack * WEIGHTS["min_staff"])
            missing_staff_vars[(d, s)] = slack

    # Seniority Rule: At least 1 Senior per Night shift
    for d in days:
        seniors_on_night = sum(x[(emp.id, d, "N")] for emp in employees if emp.is_senior)
        v_senior = model.NewBoolVar(f"v_senior_{d}")
        model.Add(seniors_on_night >= 1).OnlyEnforceIf(v_senior.Not())
        model.Add(seniors_on_night == 0).OnlyEnforceIf(v_senior)
        penalties.append(v_senior * WEIGHTS["senior"])
        violation_msgs.append((v_senior, f"Day {d+1}: Night shift missing Senior"))

    # Add small random cost to vary the results across different runs
    for var in x.values():
        penalties.append(var * random.randint(0, 5))

    # ================= 5. SOLVER CONFIGURATION =================
    model.Minimize(sum(penalties))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10
    solver.parameters.num_search_workers = 8
    
    status = solver.Solve(model)

    # ================= 6. RESULT PROCESSING =================
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        messages = []
        
        # Collect soft constraint violation messages
        for v, msg in violation_msgs:
            if solver.Value(v):
                messages.append(msg)

        for (d, s), slack in missing_staff_vars.items():
            val = solver.Value(slack)
            if val > 0:
                messages.append(f"Day {d+1}, Shift {s}: Missing {val} staff")

        # Build schedule JSON
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
            "message": "Schedule generated successfully"
        }

    return {
        "status": "error",
        "message": "No feasible schedule found satisfying hard constraints (Fixed/Off)."
    }

def generate_schedule(request) -> Dict:
    """Wrapper function for generation"""
    return generate_or_validate_schedule(request, is_validation=False)