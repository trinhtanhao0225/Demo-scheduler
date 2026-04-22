from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any


# ================= EMPLOYEE =================
class Employee(BaseModel):
    id: str
    name: str
    role: str
    is_senior: bool = False
    weekly_max_hours: int = 40
    preferred_shifts: Optional[Dict[str, List[int]]] = {}


class EmployeeInShift(BaseModel):
    id: str
    name: str
    role: str
    is_senior: bool


# ================= CONSTRAINT =================
class ConstraintItem(BaseModel):
    employee_id: str
    day: int
    shift: str


class Constraints(BaseModel):
    fixed_assignments: List[ConstraintItem] = Field(default_factory=list)
    days_off: List[ConstraintItem] = Field(default_factory=list)


# ================= REQUEST =================
class GenerateScheduleRequest(BaseModel):
    employees: List[Employee]
    num_days: int
    min_staff: Dict[str, int] = Field(default_factory=lambda: {"M": 2, "E": 2, "N": 1})
    start_date: Optional[str] = "2026-04-20"

    # manual (drag & drop)
    manual_schedule: Optional[Dict[str, Dict[str, List[EmployeeInShift]]]] = None

    # 🔥 QUAN TRỌNG (FIX LỖI CỦA BẠN)
    constraints: Optional[Constraints] = None
    use_constraints: Optional[bool] = True

# ================= RESPONSE =================
class ScheduleResponse(BaseModel):
    schedule: Dict[str, Dict[str, List[EmployeeInShift]]]
    statistics: Dict[str, Any]
    total_cost_score: float
    message: str
    status: str = "success"
    preferred_shifts: Optional[Dict[str, List[int]]] = None