from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any

class Employee(BaseModel):
    id: str
    name: str
    role: str
    is_senior: bool = False
    weekly_max_hours: int = 40

class EmployeeInShift(BaseModel):
    id: str
    name: str
    role: str
    is_senior: bool

class GenerateScheduleRequest(BaseModel):
    employees: List[Employee]
    num_days: int
    min_staff: Dict[str, int] = Field(default_factory=lambda: {"M": 2, "E": 2, "N": 1})
    start_date: Optional[str] = "2026-04-20"
    manual_schedule: Optional[Dict[str, Dict[str, List[EmployeeInShift]]]] = None

class ScheduleResponse(BaseModel):
    schedule: Dict[str, Dict[str, List[EmployeeInShift]]]
    statistics: Dict[str, Any]
    total_cost_score: float
    message: str
    status: str = "success"
    preferred_shifts: Optional[Dict[str, List[int]]] = None